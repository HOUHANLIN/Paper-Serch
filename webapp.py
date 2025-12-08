import json
import os
import re
from typing import Dict, List, Tuple

from flask import Flask, Response, render_template, request

from ai_providers.registry import get_provider, list_providers
from paper_sources import ArticleInfo
from paper_sources.registry import get_source, list_sources
from services.bibtex import build_bibtex_entries
from services.env_loader import get_env_int, load_env

app = Flask(__name__)

# 尝试从 .env 读取默认配置
load_env()


# ---------- 辅助函数 ----------

def _get_default_years(source_name: str) -> int:
    prefix = source_name.upper()
    return get_env_int(f"{prefix}_YEARS", get_env_int("PUBMED_YEARS", 5))


def _get_default_max_results(source_name: str) -> int:
    prefix = source_name.upper()
    return get_env_int(f"{prefix}_MAX_RESULTS", get_env_int("PUBMED_MAX_RESULTS", 5))


def _get_default_email(source_name: str) -> str:
    prefix = source_name.upper()
    return os.environ.get(f"{prefix}_EMAIL") or os.environ.get("PUBMED_EMAIL", "")


def _get_default_api_key(source_name: str) -> str:
    prefix = source_name.upper()
    return (
        os.environ.get(f"{prefix}_API_KEY")
        or os.environ.get("PUBMED_API_KEY")
        or os.environ.get("NCBI_API_KEY")
        or ""
    )


def _get_source_defaults(source_name: str) -> Dict[str, str | int]:
    return {
        "years": _get_default_years(source_name),
        "max_results": _get_default_max_results(source_name),
        "email": _get_default_email(source_name),
        "api_key": _get_default_api_key(source_name),
        "output": (
            os.environ.get(f"{source_name.upper()}_OUTPUT")
            or os.environ.get("PUBMED_OUTPUT")
            or "pubmed_results.bib"
        ),
    }


def _default_source_name() -> str:
    sources = list_sources()
    return sources[0].name if sources else ""


def _default_ai_provider_name() -> str:
    providers = list_providers()
    for provider in providers:
        if provider.name == "gemini":
            return provider.name
    for provider in providers:
        if provider.name != "none":
            return provider.name
    return providers[0].name if providers else "none"


def _default_query(source_name: str) -> str:
    prefix = source_name.upper()
    env_query = (
        os.environ.get(f"{prefix}_QUERY")
        or os.environ.get("QUERY")
        or os.environ.get("PUBMED_QUERY")
    )
    if env_query:
        return env_query
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


def _apply_ai_summary(infos: List[ArticleInfo], provider_name: str) -> None:
    provider = get_provider(provider_name)
    if not provider or provider.name == "none":
        return
    for info in infos:
        summary = provider.summarize(info)
        if summary:
            info.annote, _, _ = _normalize_annote(summary)


def _perform_search(
    *,
    source_name: str,
    query: str,
    years: int,
    max_results: int,
    email: str,
    api_key: str,
    ai_provider: str,
) -> Tuple[str, int, List[ArticleInfo]]:
    source = get_source(source_name)
    if not source:
        raise RuntimeError(f"未找到名为 {source_name} 的文献数据源")

    articles = source.search(
        query=query,
        years=years,
        max_results=max_results,
        email=email or None,
        api_key=api_key or None,
    )
    if not articles:
        return "", 0, []

    _apply_ai_summary(articles, ai_provider)

    # 清理 annote，去掉冗余符号便于 BibTeX 展示
    for info in articles:
        info.annote, _, _ = _normalize_annote(info.annote)

    bibtex_text, count = build_bibtex_entries(articles)
    return bibtex_text, count, articles


def _parse_int(value: str, default_value: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


def _resolve_form(form_data) -> Tuple[Dict[str, str], Dict[str, str | int]]:
    """返回渲染用的表单值以及用于搜索的解析结果。"""

    source = (form_data.get("source") or _default_source_name()).strip()
    defaults = _get_source_defaults(source)

    ai_provider = (form_data.get("ai_provider") or _default_ai_provider_name()).strip()
    query = (form_data.get("query") or _default_query(source)).strip()
    years_raw = (form_data.get("years") or "").strip()
    max_results_raw = (form_data.get("max_results") or "").strip()
    email_raw = (form_data.get("email") or "").strip()
    api_key_raw = (form_data.get("api_key") or "").strip()

    resolved = {
        "source": source,
        "ai_provider": ai_provider,
        "query": query,
        "years": _parse_int(years_raw, defaults["years"]),
        "max_results": _parse_int(max_results_raw, defaults["max_results"]),
        "email": email_raw or defaults["email"],
        "api_key": api_key_raw or defaults["api_key"],
    }

    form = {
        "source": source,
        "ai_provider": ai_provider,
        "query": query,
        "years": years_raw,
        "max_results": max_results_raw,
        "email": email_raw,
        "api_key": api_key_raw,
    }

    return form, resolved


# ---------- 路由 ----------


@app.route("/", methods=["GET", "POST"])
def index():
    error = ""
    bibtex_text = ""
    count = 0
    articles: List[Dict[str, str]] = []

    sources = list_sources()
    ai_providers = list_providers()

    form, resolved = _resolve_form(request.form if request.method == "POST" else {})

    if request.method == "POST":
        if not resolved["query"]:
            error = "请输入检索式。"
        else:
            try:
                bibtex_text, count, found_articles = _perform_search(
                    source_name=resolved["source"],
                    query=resolved["query"],
                    years=resolved["years"],
                    max_results=resolved["max_results"],
                    email=resolved["email"],
                    api_key=resolved["api_key"],
                    ai_provider=resolved["ai_provider"],
                )
                articles = [_build_view_article(info) for info in found_articles]
                if not count:
                    error = "没有检索到符合条件的文献。"
            except Exception as exc:  # pylint: disable=broad-except
                error = f"检索或生成 BibTeX 时出错：{exc}"

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
    )


@app.route("/download", methods=["POST"])
def download():
    """根据前端表单参数重新检索并返回 BibTeX 文件。"""
    _, resolved = _resolve_form(request.form)

    if not resolved["query"]:
        return "缺少检索式。", 400

    try:
        bibtex_text, count, _ = _perform_search(
            source_name=resolved["source"],
            query=resolved["query"],
            years=resolved["years"],
            max_results=resolved["max_results"],
            email=resolved["email"],
            api_key=resolved["api_key"],
            ai_provider=resolved["ai_provider"],
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"检索或生成 BibTeX 时出错：{exc}", 500

    if not count:
        return "没有检索到符合条件的文献。", 404

    filename = _get_source_defaults(resolved["source"])["output"]
    resp = Response(bibtex_text, mimetype="application/x-bibtex; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


if __name__ == "__main__":
    app.run(debug=True)
