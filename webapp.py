import json
import os
import re
import secrets
from typing import Dict, Generator, List, Optional, Tuple

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from openai import OpenAI

from ai_providers.gemini import GeminiProvider
from ai_providers.openai_provider import OpenAIProvider
from ai_providers.registry import get_provider, list_providers
from paper_sources import ArticleInfo
from paper_sources.registry import get_source, list_sources
from services.bibtex import build_bibtex_entries

app = Flask(__name__)


# ---------- 辅助函数 ----------

def _get_default_years(source_name: str) -> int:
    return 5


def _get_default_max_results(source_name: str) -> int:
    return 5


def _generate_random_email() -> str:
    """生成一个用于 PubMed 请求的随机邮箱地址。"""
    local_part = f"user_{secrets.token_hex(4)}"
    domain = os.environ.get("DEFAULT_EMAIL_DOMAIN") or "example.com"
    return f"{local_part}@{domain}"


def _get_default_email(source_name: str) -> str:
    return ""


def _get_default_api_key(source_name: str) -> str:
    return ""


def _status_log_entry(step: str, status: str, detail: str) -> Dict[str, str]:
    return {"step": step, "status": status, "detail": detail}


def _sse_message(event: str, data: Dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_source_defaults(source_name: str) -> Dict[str, str | int]:
    return {
        "years": _get_default_years(source_name),
        "max_results": _get_default_max_results(source_name),
        "email": _get_default_email(source_name),
        "api_key": _get_default_api_key(source_name),
        "output": "pubmed_results.bib",
    }


def _default_source_name() -> str:
    sources = list_sources()
    return sources[0].name if sources else ""


def _default_ai_provider_name() -> str:
    providers = list_providers()
    for provider in providers:
        if provider.name == "none":
            return provider.name
    return providers[0].name if providers else "none"


def _default_query(source_name: str) -> str:
    return (
        '"artificial intelligence" AND ("dental implants" OR "implant dentistry" OR "oral implantology")'
    )


def _normalize_annote(raw: str) -> Tuple[str, str, str]:
    """尝试从 annote 中提取 summary/usage，并移除额外符号。"""
    text = (raw or "").strip()
    if not text:
        return "", "", ""

    candidates = []

    def _add_candidate(val: str) -> None:
        if val and val not in candidates:
            candidates.append(val)

    _add_candidate(text)

    # 去掉围绕 JSON 的代码块符号
    fence_trimmed = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    _add_candidate(fence_trimmed)

    # 提取花括号内的 JSON 片段
    match = re.search(r"\{.*\}", fence_trimmed, flags=re.DOTALL)
    if match:
        _add_candidate(match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            summary = str(parsed.get("summary_zh") or "").strip()
            usage = str(parsed.get("usage_zh") or "").strip()
            normalized_json = json.dumps(
                {k: v for k, v in (("summary_zh", summary), ("usage_zh", usage)) if v},
                ensure_ascii=False,
            )
            return normalized_json, summary, usage

    return fence_trimmed, fence_trimmed, ""


def _build_view_article(info: ArticleInfo) -> Dict[str, str]:
    annote, summary_zh, usage_zh = _normalize_annote(info.annote)
    info.annote = annote

    return {
        "title": info.title or "(无标题)",
        "authors": info.authors,
        "journal": info.journal,
        "year": info.year,
        "abstract": info.abstract,
        "url": info.url,
        "pmid": info.pmid,
        "summary_zh": summary_zh,
        "usage_zh": usage_zh,
    }


def _apply_ai_summary(
    infos: List[ArticleInfo],
    provider_name: str,
    gemini_api_key: str,
    gemini_model: str,
    gemini_temperature: float,
    openai_api_key: str,
    openai_base_url: str,
    openai_model: str,
    openai_temperature: float,
) -> str:
    provider = get_provider(provider_name)
    if not provider or provider.name == "none":
        return "已跳过 AI 总结（未选择模型）"

    if isinstance(provider, GeminiProvider):
        provider.set_config(
            api_key=gemini_api_key or None,
            model=gemini_model or None,
            temperature=gemini_temperature,
        )
    if isinstance(provider, OpenAIProvider):
        provider.set_config(
            api_key=openai_api_key or None,
            base_url=openai_base_url or None,
            model=openai_model or None,
            temperature=openai_temperature,
        )

    applied = 0
    for info in infos:
        summary = provider.summarize(info)
        if summary:
            info.annote, _, _ = _normalize_annote(summary)
            applied += 1
    if applied:
        return f"已使用 {provider.display_name} 生成 {applied} 条摘要"
    return "AI 未返回摘要，可能未配置模型或接口未返回内容"


def _perform_search_stream(
    *,
    source: str,
    query: str,
    years: int,
    max_results: int,
    email: str,
    api_key: str,
    ai_provider: str,
    gemini_api_key: str,
    gemini_model: str,
    gemini_temperature: float,
    openai_api_key: str,
    openai_base_url: str,
    openai_model: str,
    openai_temperature: float,
    output: str,
) -> Generator[Dict[str, object], None, None]:
    status_log: List[Dict[str, str]] = []

    def _emit(step: str, status: str, detail: str) -> Dict[str, str]:
        entry = _status_log_entry(step, status, detail)
        status_log.append(entry)
        return entry

    try:
        source_obj = get_source(source)
        if not source_obj:
            raise RuntimeError(f"未找到名为 {source} 的文献数据源")

        yield {"type": "status", "entry": _emit("准备检索", "success", f"数据源：{source_obj.display_name}")}
        yield {"type": "status", "entry": _emit("检索中", "running", "正在向数据源获取文献...")}

        articles = source_obj.search(
            query=query,
            years=years,
            max_results=max_results,
            email=email or None,
            api_key=api_key or None,
        )
        if not articles:
            yield {
                "type": "status",
                "entry": _emit("检索完成", "error", "没有找到符合条件的记录"),
                "status_log": status_log,
            }
            yield {"type": "error", "message": "没有找到符合条件的记录", "status_log": status_log}
            return

        yield {
            "type": "status",
            "entry": _emit("检索完成", "success", f"共获取 {len(articles)} 条候选文献"),
        }

        if ai_provider and ai_provider != "none":
            yield {"type": "status", "entry": _emit("AI 摘要", "running", "正在生成摘要...")}
        try:
            ai_status = _apply_ai_summary(
                articles,
                ai_provider,
                gemini_api_key,
                gemini_model,
                gemini_temperature,
                openai_api_key,
                openai_base_url,
                openai_model,
                openai_temperature,
            )
            ai_entry_status = "success" if "失败" not in ai_status else "error"
            yield {"type": "status", "entry": _emit("AI 摘要", ai_entry_status, ai_status)}
            if ai_entry_status == "error":
                yield {"type": "error", "message": ai_status, "status_log": status_log}
                return
        except Exception as exc:  # pylint: disable=broad-except
            failure_detail = f"AI 摘要失败：{exc}"
            yield {
                "type": "status",
                "entry": _emit("AI 摘要", "error", failure_detail),
                "status_log": status_log,
            }
            yield {"type": "error", "message": failure_detail, "status_log": status_log}
            return

        for info in articles:
            info.annote, _, _ = _normalize_annote(info.annote)

        yield {"type": "status", "entry": _emit("BibTeX 生成", "running", "正在整理文献并生成 BibTeX...")}
        bibtex_text, count = build_bibtex_entries(articles)
        yield {"type": "status", "entry": _emit("BibTeX 生成", "success", f"生成 {count} 条记录")}

        view_articles = [_build_view_article(info) for info in articles]
        yield {
            "type": "result",
            "bibtex_text": bibtex_text,
            "count": count,
            "articles": view_articles,
            "status_log": status_log,
        }
    except Exception as exc:  # pylint: disable=broad-except
        yield {
            "type": "status",
            "entry": _emit("流程中断", "error", str(exc)),
            "status_log": status_log,
        }
        yield {"type": "error", "message": str(exc), "status_log": status_log}


def _parse_int(value: str, default_value: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


def _parse_float(value: str, default_value: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default_value


def _build_pubmed_query_by_rules(intent: str) -> str:
    intent_clean = intent.strip()
    if not intent_clean:
        return ""

    # 将中文和英文的“或”分组视为同义词，分号/逗号断开主概念，再用 AND 连接
    segments = re.split(r"[；;，。,.]+", intent_clean)
    groups: List[str] = []
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        synonyms = re.split(r"\s*(?:或|或者|or|OR|/|\|)\s*", segment)
        synonym_terms: List[str] = []
        for term in synonyms:
            term_clean = term.strip()
            if not term_clean:
                continue
            # 保留原有的英文短语，引号或空格视为短语
            if " " in term_clean or "“" in term_clean or '"' in term_clean:
                synonym_terms.append(f'("{term_clean.strip("\" ")}"[Title/Abstract])')
            else:
                synonym_terms.append(f"({term_clean}[Title/Abstract])")
        if synonym_terms:
            if len(synonym_terms) == 1:
                groups.append(synonym_terms[0])
            else:
                groups.append("(" + " OR ".join(synonym_terms) + ")")
    return " AND ".join(groups)


def _generate_query_via_openai(prompt: str, api_key: str, base_url: str, model: str, temperature: float) -> str:
    try:
        client = OpenAI(api_key=api_key, base_url=base_url or None)
        completion = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": "你是检索词专家，只输出最终的检索式文本，不要解释。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=320,
        )
        content = completion.choices[0].message.content if completion.choices else ""
        return (content or "").strip()
    except Exception:
        return ""


def _generate_query_via_gemini(prompt: str, api_key: str, model: str, temperature: float) -> str:
    provider = GeminiProvider()
    provider.set_config(api_key=api_key, model=model or None, temperature=temperature)
    if not provider._ensure_client():  # pylint: disable=protected-access
        return ""
    try:
        types = provider._types  # pylint: disable=protected-access
        client = provider._client  # pylint: disable=protected-access
        if types is None or client is None:
            return ""
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
        config = types.GenerateContentConfig(temperature=temperature)
        chunks: List[str] = []
        for chunk in client.models.generate_content_stream(model=provider.model, contents=contents, config=config):
            text = getattr(chunk, "text", "") or ""
            if text:
                chunks.append(text)
        return " ".join(chunks).strip()
    except Exception:
        return ""


def _generate_query_terms(
    *,
    source_name: str,
    intent: str,
    ai_provider: str,
    gemini_api_key: str,
    gemini_model: str,
    gemini_temperature: float,
    openai_api_key: str,
    openai_base_url: str,
    openai_model: str,
    openai_temperature: float,
) -> Tuple[str, str]:
    def _normalize(value: str) -> str:
        return (value or "").strip()

    def _normalize_optional(value: str) -> Optional[str]:
        value_clean = (value or "").strip()
        return value_clean or None

    intent_clean = (intent or "").strip()
    if not intent_clean:
        return "", "请先提供你的检索需求。"

    # 使用选定的来源提示语法
    if source_name == "pubmed":
        syntax_hint = (
            "请输出 PubMed 检索式：概念用 AND 连接，同义词用 OR 连接，短语加引号，"
            "并可使用 [Title/Abstract] 字段限制。不要添加额外解释。"
        )
    else:
        syntax_hint = "请给出适配所选文献站点的检索式，不要额外解释。"

    prompt = (
        f"用户需求：{intent_clean}\n"
        f"目标站点：{source_name}\n"
        f"格式要求：{syntax_hint}\n"
        "请直接返回最终检索式。"
    )

    openai_defaults = OpenAIProvider()
    resolved_openai_api_key = _normalize(openai_api_key) or (openai_defaults.api_key or "")
    resolved_openai_base_url = _normalize_optional(openai_base_url) or openai_defaults.base_url or ""
    resolved_openai_model = _normalize(openai_model) or openai_defaults.model
    resolved_openai_temperature = openai_temperature if openai_temperature is not None else openai_defaults.temperature

    gemini_defaults = GeminiProvider()
    resolved_gemini_api_key = _normalize(gemini_api_key) or (gemini_defaults.api_key or "")
    resolved_gemini_model = _normalize(gemini_model) or gemini_defaults.model
    resolved_gemini_temperature = gemini_temperature if gemini_temperature is not None else gemini_defaults.temperature

    if ai_provider == "openai":
        if not resolved_openai_api_key:
            return "", "未配置 OpenAI API Key，无法调用真实接口生成检索式。"
        ai_query = _generate_query_via_openai(
            prompt,
            resolved_openai_api_key,
            resolved_openai_base_url,
            resolved_openai_model,
            resolved_openai_temperature,
        )
        if ai_query:
            return ai_query, "已使用 OpenAI 实时生成的检索式"
        return "", "OpenAI 生成检索式失败，请检查配置。"

    if ai_provider == "gemini":
        if not resolved_gemini_api_key:
            return "", "未配置 Gemini API Key，无法调用真实接口生成检索式。"
        ai_query = _generate_query_via_gemini(
            prompt,
            resolved_gemini_api_key,
            resolved_gemini_model,
            resolved_gemini_temperature,
        )
        if ai_query:
            return ai_query, "已使用 Gemini 实时生成的检索式"
        return "", "Gemini 生成检索式失败，请检查配置。"

    # fallback to rule-based builder when AI 不可用
    if source_name == "pubmed":
        return _build_pubmed_query_by_rules(intent_clean), "已按规则生成 PubMed 检索式"

    return intent_clean, "已返回原始输入"


def _resolve_form(form_data) -> Tuple[Dict[str, str], Dict[str, object]]:
    """返回渲染用的表单值以及用于搜索的解析结果。"""

    source = (form_data.get("source") or _default_source_name()).strip()
    defaults = _get_source_defaults(source)

    ai_provider = (form_data.get("ai_provider") or _default_ai_provider_name()).strip()
    query = (form_data.get("query") or _default_query(source)).strip()
    years_raw = (form_data.get("years") or "").strip()
    max_results_raw = (form_data.get("max_results") or "").strip()
    email_raw = (form_data.get("email") or "").strip()
    api_key_raw = (form_data.get("api_key") or "").strip()
    output_raw = (form_data.get("output") or "").strip()
    gemini_api_key_raw = (form_data.get("gemini_api_key") or "").strip()
    gemini_model_raw = (form_data.get("gemini_model") or "").strip()
    gemini_temperature_raw = (form_data.get("gemini_temperature") or "").strip()
    openai_api_key_raw = (form_data.get("openai_api_key") or "").strip()
    openai_base_url_raw = (form_data.get("openai_base_url") or "").strip()
    openai_model_raw = (form_data.get("openai_model") or "").strip()
    openai_temperature_raw = (form_data.get("openai_temperature") or "").strip()

    # 默认邮箱解析逻辑：
    # 1. 若用户在表单中填写，则优先使用用户输入。
    # 2. 若留空，则在本次请求中生成一个随机邮箱；
    #    注意这个随机邮箱不写回表单，保证用户视角下输入框始终为空，
    #    且“每一次请求 API（在邮箱留空的情况下）都会生成新的邮箱”。
    if email_raw:
        resolved_email = email_raw
    elif defaults["email"]:
        resolved_email = defaults["email"]
    else:
        resolved_email = _generate_random_email()

    resolved_output = output_raw or str(defaults["output"])
    resolved_temperature = _parse_float(gemini_temperature_raw, 0.0)

    resolved = {
        "source": source,
        "ai_provider": ai_provider,
        "query": query,
        "years": _parse_int(years_raw, defaults["years"]),
        "max_results": _parse_int(max_results_raw, defaults["max_results"]),
        "email": resolved_email,
        "api_key": api_key_raw or defaults["api_key"],
        "output": resolved_output,
        "gemini_api_key": gemini_api_key_raw,
        "gemini_model": gemini_model_raw,
        "gemini_temperature": resolved_temperature,
        "openai_api_key": openai_api_key_raw,
        "openai_base_url": openai_base_url_raw,
        "openai_model": openai_model_raw,
        "openai_temperature": _parse_float(openai_temperature_raw, 0.0),
    }

    form = {
        "source": source,
        "ai_provider": ai_provider,
        "query": query,
        "years": years_raw,
        "max_results": max_results_raw,
        # 表单中只回显用户输入；如果用户留空，则始终显示为空，
        # 但后台每次请求都会在需要时生成一个新的随机邮箱用于 PubMed 请求。
        "email": email_raw,
        "api_key": api_key_raw,
        "output": output_raw,
        "gemini_api_key": gemini_api_key_raw,
        "gemini_model": gemini_model_raw,
        "gemini_temperature": gemini_temperature_raw,
        "openai_api_key": openai_api_key_raw,
        "openai_base_url": openai_base_url_raw,
        "openai_model": openai_model_raw,
        "openai_temperature": openai_temperature_raw,
    }

    return form, resolved


def _consume_search_stream(resolved: Dict[str, object]) -> Tuple[str, str, int, List[Dict[str, str]], List[Dict[str, str]]]:
    error = ""
    bibtex_text = ""
    count = 0
    articles: List[Dict[str, str]] = []
    status_log: List[Dict[str, str]] = []

    for event in _perform_search_stream(**resolved):
        if event.get("type") == "status" and event.get("entry"):
            status_log.append(event["entry"])
        if event.get("type") == "result":
            bibtex_text = str(event.get("bibtex_text") or "")
            count = int(event.get("count") or 0)
            articles = event.get("articles") or []
        if event.get("type") == "error" and event.get("message"):
            error = str(event.get("message"))
    return error, bibtex_text, count, articles, status_log


# ---------- 路由 ----------


@app.route("/", methods=["GET", "POST"])
def index():
    error = ""
    bibtex_text = ""
    count = 0
    articles: List[Dict[str, str]] = []
    status_log: List[Dict[str, str]] = []

    sources = list_sources()
    ai_providers = list_providers()

    form, resolved = _resolve_form(request.form if request.method == "POST" else {})

    if request.method == "POST":
        if not resolved["query"]:
            error = "请输入检索式。"
        else:
            try:
                error, bibtex_text, count, articles, status_log = _consume_search_stream(resolved)
            except Exception as exc:  # pylint: disable=broad-except
                error = f"检索或生成 BibTeX 时出错：{exc}"
                status_log.append(_status_log_entry("流程中断", "error", str(exc)))

    source_defaults = {source.name: _get_source_defaults(source.name) for source in sources}

    return render_template(
        "index.html",
        form=form,
        error=error,
        bibtex_text=bibtex_text,
        count=count,
        articles=articles,
        sources=sources,
        ai_providers=ai_providers,
        source_defaults=source_defaults,
        status_log=status_log,
    )


@app.route("/download", methods=["POST"])
def download():
    """根据结果框中的 BibTeX 文本直接生成文件，避免重复调用外部 API。"""
    bibtex_text = (request.form.get("bibtex_text") or "").strip()
    if not bibtex_text:
        return "缺少 BibTeX 内容，请先生成结果。", 400

    source = (request.form.get("source") or _default_source_name()).strip()
    output_name = (request.form.get("output") or "").strip()
    if not output_name:
        output_name = str(_get_source_defaults(source)["output"])
    filename = output_name
    resp = Response(bibtex_text, mimetype="application/x-bibtex; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@app.route("/api/generate_query", methods=["POST"])
def generate_query():
    data = request.get_json(force=True, silent=True) or {}
    intent = data.get("intent") or ""
    source = (data.get("source") or _default_source_name()).strip()
    ai_provider = (data.get("ai_provider") or _default_ai_provider_name()).strip()
    query, message = _generate_query_terms(
        source_name=source,
        intent=intent,
        ai_provider=ai_provider,
        gemini_api_key=(data.get("gemini_api_key") or "").strip(),
        gemini_model=(data.get("gemini_model") or "").strip(),
        gemini_temperature=_parse_float(data.get("gemini_temperature"), 0.0),
        openai_api_key=(data.get("openai_api_key") or "").strip(),
        openai_base_url=(data.get("openai_base_url") or "").strip(),
        openai_model=(data.get("openai_model") or "").strip(),
        openai_temperature=_parse_float(data.get("openai_temperature"), 0.0),
    )
    return jsonify({"query": query, "message": message})


@app.route("/api/search_stream", methods=["POST"])
def search_stream():
    form_data = request.form or {}
    _, resolved = _resolve_form(form_data)

    def event_stream():
        for event in _perform_search_stream(**resolved):
            event_type = str(event.get("type") or "message")
            payload = {k: v for k, v in event.items() if k != "type"}
            yield _sse_message(event_type, payload)

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    return Response(stream_with_context(event_stream()), mimetype="text/event-stream", headers=headers)


@app.route("/tutorial", methods=["GET"])
def tutorial():
    sources = list_sources()
    ai_providers = list_providers()
    return render_template(
        "tutorial.html",
        sources=sources,
        ai_providers=ai_providers,
    )


if __name__ == "__main__":
    app.run(debug=True)
