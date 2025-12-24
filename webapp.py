import json
import os
import secrets
from typing import Dict, Generator, List, Tuple

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from ai_providers.registry import list_providers
from paper_sources import ArticleInfo
from paper_sources.registry import get_source, list_sources
from services.bibtex import build_bibtex_entries
from services.ai_query import generate_query_terms
from services.ai_summary import apply_ai_summary, normalize_annote
from services.directions import extract_search_directions

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
    return "openai"


def _default_query(source_name: str) -> str:
    return (
        '"artificial intelligence" AND ("dental implants" OR "implant dentistry" OR "oral implantology")'
    )


def _build_view_article(info: ArticleInfo) -> Dict[str, str]:
    annote, summary_zh, usage_zh = normalize_annote(info.annote)
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
    ollama_api_key: str,
    ollama_base_url: str,
    ollama_model: str,
    ollama_temperature: float,
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

        ai_failed = False
        if ai_provider:
            yield {"type": "status", "entry": _emit("AI 摘要", "running", "正在生成摘要...")}
            try:
                ai_status = apply_ai_summary(
                    articles,
                    ai_provider,
                    gemini_api_key,
                    gemini_model,
                    gemini_temperature,
                    openai_api_key,
                    openai_base_url,
                    openai_model,
                    openai_temperature,
                    ollama_api_key,
                    ollama_base_url,
                    ollama_model,
                    ollama_temperature,
                )
                ai_entry_status = "success" if "失败" not in ai_status else "error"
            except Exception as exc:  # pylint: disable=broad-except
                ai_status = f"AI 摘要失败：{exc}"
                ai_entry_status = "error"

            yield {"type": "status", "entry": _emit("AI 摘要", ai_entry_status, ai_status)}
            ai_failed = ai_entry_status == "error"

        for info in articles:
            info.annote, _, _ = normalize_annote(info.annote)

        yield {"type": "status", "entry": _emit("BibTeX 生成", "running", "正在整理文献并生成 BibTeX...")}
        bibtex_text, count = build_bibtex_entries(articles)
        yield {"type": "status", "entry": _emit("BibTeX 生成", "success", f"生成 {count} 条记录")}

        if ai_failed:
            status_log.append(
                _status_log_entry("AI 摘要", "error", "AI 摘要失败，已返回未总结的结果")
            )

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
    ollama_api_key_raw = (form_data.get("ollama_api_key") or "").strip()
    ollama_base_url_raw = (form_data.get("ollama_base_url") or "").strip()
    ollama_model_raw = (form_data.get("ollama_model") or "").strip()
    ollama_temperature_raw = (form_data.get("ollama_temperature") or "").strip()

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
        "ollama_api_key": ollama_api_key_raw,
        "ollama_base_url": ollama_base_url_raw,
        "ollama_model": ollama_model_raw,
        "ollama_temperature": _parse_float(ollama_temperature_raw, 0.0),
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
        "ollama_api_key": ollama_api_key_raw,
        "ollama_base_url": ollama_base_url_raw,
        "ollama_model": ollama_model_raw,
        "ollama_temperature": ollama_temperature_raw,
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


def _prefix_status(direction: str, entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    prefixed: List[Dict[str, str]] = []
    for entry in entries:
        prefixed.append(
            {
                "step": f"[{direction}] {entry.get('step', '')}",
                "status": entry.get("status", ""),
                "detail": entry.get("detail", ""),
            }
        )
    return prefixed


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


@app.route("/workflow", methods=["GET"])
def workflow():
    sources = list_sources()
    ai_providers = list_providers()
    form, _ = _resolve_form({})
    source_defaults = {source.name: _get_source_defaults(source.name) for source in sources}

    return render_template(
        "workflow.html",
        form=form,
        sources=sources,
        ai_providers=ai_providers,
        source_defaults=source_defaults,
        status_log=[],
        bibtex_text="",
        count=0,
        articles=[],
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
    query, message = generate_query_terms(
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
        ollama_api_key=(data.get("ollama_api_key") or "").strip(),
        ollama_base_url=(data.get("ollama_base_url") or "").strip(),
        ollama_model=(data.get("ollama_model") or "").strip(),
        ollama_temperature=_parse_float(data.get("ollama_temperature"), 0.0),
    )
    return jsonify({"query": query, "message": message})


@app.route("/api/auto_workflow", methods=["POST"])
def auto_workflow():
    data = request.get_json(force=True, silent=True) or {}
    source = (data.get("source") or _default_source_name()).strip()
    direction_ai_provider = (data.get("direction_ai_provider") or data.get("ai_provider") or _default_ai_provider_name()).strip()
    query_ai_provider = (data.get("query_ai_provider") or direction_ai_provider).strip()
    summary_ai_provider = (data.get("summary_ai_provider") or data.get("ai_provider") or _default_ai_provider_name()).strip()
    years = _parse_int(data.get("years"), _get_default_years(source))
    max_results = max(1, _parse_int(data.get("max_results_per_direction") or data.get("max_results"), 3))

    directions, extraction_message = extract_search_directions(
        content=data.get("content") or "",
        ai_provider=direction_ai_provider,
        gemini_api_key=(data.get("gemini_api_key") or "").strip(),
        gemini_model=(data.get("gemini_model") or "").strip(),
        gemini_temperature=_parse_float(data.get("gemini_temperature"), 0.0),
        openai_api_key=(data.get("openai_api_key") or "").strip(),
        openai_base_url=(data.get("openai_base_url") or "").strip(),
        openai_model=(data.get("openai_model") or "").strip(),
        openai_temperature=_parse_float(data.get("openai_temperature"), 0.0),
        ollama_api_key=(data.get("ollama_api_key") or "").strip(),
        ollama_base_url=(data.get("ollama_base_url") or "").strip(),
        ollama_model=(data.get("ollama_model") or "").strip(),
        ollama_temperature=_parse_float(data.get("ollama_temperature"), 0.0),
    )

    status_log: List[Dict[str, str]] = []
    if not directions:
        status_log.append(_status_log_entry("提取方向", "error", extraction_message))
        return jsonify({"error": extraction_message, "status_log": status_log}), 400
    status_log.append(_status_log_entry("提取方向", "success", extraction_message))

    combined_bibtex_parts: List[str] = []
    combined_articles: List[Dict[str, str]] = []
    direction_details: List[Dict[str, object]] = []
    total_count = 0

    max_query_retries = 3

    for direction in directions:
        direction_status_log = [_status_log_entry("检索方向", "running", direction)]
        query, query_message = generate_query_terms(
            source_name=source,
            intent=direction,
            ai_provider=query_ai_provider,
            gemini_api_key=(data.get("gemini_api_key") or "").strip(),
            gemini_model=(data.get("gemini_model") or "").strip(),
            gemini_temperature=_parse_float(data.get("gemini_temperature"), 0.0),
            openai_api_key=(data.get("openai_api_key") or "").strip(),
            openai_base_url=(data.get("openai_base_url") or "").strip(),
            openai_model=(data.get("openai_model") or "").strip(),
            openai_temperature=_parse_float(data.get("openai_temperature"), 0.0),
            ollama_api_key=(data.get("ollama_api_key") or "").strip(),
            ollama_base_url=(data.get("ollama_base_url") or "").strip(),
            ollama_model=(data.get("ollama_model") or "").strip(),
            ollama_temperature=_parse_float(data.get("ollama_temperature"), 0.0),
        )

        if not query:
            direction_status_log.append(_status_log_entry("生成检索式", "error", query_message))
            prefixed = _prefix_status(direction, direction_status_log)
            status_log.extend(prefixed)
            direction_details.append(
                {
                    "direction": direction,
                    "query": "",
                    "message": query_message,
                    "error": query_message,
                    "status_log": prefixed,
                }
            )
            continue

        direction_status_log.append(_status_log_entry("生成检索式", "success", query_message))

        current_query = query
        current_query_message = query_message
        retry_count = 0
        search_error = ""
        bibtex_text = ""
        count = 0
        articles: List[Dict[str, str]] = []

        while True:
            resolved_payload = {
                "source": source,
                "query": current_query,
                "years": str(years),
                "max_results": str(max_results),
                "ai_provider": summary_ai_provider,
                "email": (data.get("email") or "").strip(),
                "api_key": (data.get("api_key") or "").strip(),
                "output": (data.get("output") or "").strip(),
                "gemini_api_key": (data.get("gemini_api_key") or "").strip(),
                "gemini_model": (data.get("gemini_model") or "").strip(),
                "gemini_temperature": data.get("gemini_temperature") or "0",
                "openai_api_key": (data.get("openai_api_key") or "").strip(),
                "openai_base_url": (data.get("openai_base_url") or "").strip(),
                "openai_model": (data.get("openai_model") or "").strip(),
                "openai_temperature": data.get("openai_temperature") or "0",
                "ollama_api_key": (data.get("ollama_api_key") or "").strip(),
                "ollama_base_url": (data.get("ollama_base_url") or "").strip(),
                "ollama_model": (data.get("ollama_model") or "").strip(),
                "ollama_temperature": data.get("ollama_temperature") or "0",
            }
            _, resolved = _resolve_form(resolved_payload)
            search_error, bibtex_text, count, articles, search_status_log = _consume_search_stream(resolved)
            direction_status_log.extend(search_status_log)

            # 检索成功或非空结果则跳出循环
            if not search_error:
                break
            if count > 0:
                break

            if retry_count >= max_query_retries:
                break

            retry_count += 1
            retry_prompt = (
                f"{direction}\n"
                f"原检索式未能检索到结果：{current_query}\n"
                "请在不偏离主题的前提下调整或扩展关键词，给出新的检索式。"
            )
            direction_status_log.append(
                _status_log_entry("检索重试", "running", f"第 {retry_count} 次尝试改写检索式")
            )
            current_query, current_query_message = generate_query_terms(
                source_name=source,
                intent=retry_prompt,
                ai_provider=query_ai_provider,
                gemini_api_key=(data.get("gemini_api_key") or "").strip(),
                gemini_model=(data.get("gemini_model") or "").strip(),
                gemini_temperature=_parse_float(data.get("gemini_temperature"), 0.0),
                openai_api_key=(data.get("openai_api_key") or "").strip(),
                openai_base_url=(data.get("openai_base_url") or "").strip(),
                openai_model=(data.get("openai_model") or "").strip(),
                openai_temperature=_parse_float(data.get("openai_temperature"), 0.0),
                ollama_api_key=(data.get("ollama_api_key") or "").strip(),
                ollama_base_url=(data.get("ollama_base_url") or "").strip(),
                ollama_model=(data.get("ollama_model") or "").strip(),
                ollama_temperature=_parse_float(data.get("ollama_temperature"), 0.0),
            )

            if not current_query:
                direction_status_log.append(_status_log_entry("检索重试", "error", current_query_message))
                break

            direction_status_log.append(
                _status_log_entry("检索重试", "success", f"已生成新的检索式（重试 {retry_count}）")
            )

        prefixed = _prefix_status(direction, direction_status_log)
        status_log.extend(prefixed)

        if search_error:
            direction_details.append(
                {
                    "direction": direction,
                    "query": current_query,
                    "message": current_query_message,
                    "error": search_error,
                    "retry_count": retry_count,
                    "status_log": prefixed,
                }
            )
            continue

        combined_bibtex_parts.append(bibtex_text)
        total_count += count
        for article in articles:
            article["direction"] = direction
        combined_articles.extend(articles)
        direction_details.append(
            {
                "direction": direction,
                "query": current_query,
                "message": current_query_message,
                "count": count,
                "articles": articles,
                "bibtex_text": bibtex_text,
                "retry_count": retry_count,
                "status_log": prefixed,
            }
        )

    combined_bibtex = "\n\n".join(part.strip() for part in combined_bibtex_parts if part.strip())
    return jsonify(
        {
            "directions": direction_details,
            "status_log": status_log,
            "bibtex_text": combined_bibtex,
            "count": total_count,
            "articles": combined_articles,
            "message": extraction_message,
        }
    )


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
