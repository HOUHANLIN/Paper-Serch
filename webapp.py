import json
import os
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

def _get_default_years() -> int:
    return get_env_int("PUBMED_YEARS", 5)


def _get_default_max_results() -> int:
    return get_env_int("PUBMED_MAX_RESULTS", 10)


def _default_source_name() -> str:
    sources = list_sources()
    return sources[0].name if sources else ""


def _default_ai_provider_name() -> str:
    providers = list_providers()
    for provider in providers:
        if provider.name != "none":
            return provider.name
    return providers[0].name if providers else "none"


def _build_view_article(info: ArticleInfo) -> Dict[str, str]:
    annote_raw = (info.annote or "").strip()
    summary_zh = ""
    usage_zh = ""
    if annote_raw:
        try:
            parsed = json.loads(annote_raw)
            if isinstance(parsed, dict):
                summary_zh = str(parsed.get("summary_zh") or "").strip()
                usage_zh = str(parsed.get("usage_zh") or "").strip()
        except Exception:
            summary_zh = annote_raw

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
            info.annote = summary


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
    bibtex_text, count = build_bibtex_entries(articles)
    return bibtex_text, count, articles


# ---------- 路由 ----------


@app.route("/", methods=["GET", "POST"])
def index():
    error = ""
    bibtex_text = ""
    count = 0
    articles: List[Dict[str, str]] = []

    sources = list_sources()
    ai_providers = list_providers()

    form = {
        "source": _default_source_name(),
        "ai_provider": _default_ai_provider_name(),
        "query": os.environ.get("PUBMED_QUERY", ""),
        "years": str(_get_default_years()),
        "max_results": str(_get_default_max_results()),
        "email": os.environ.get("PUBMED_EMAIL", ""),
        "api_key": os.environ.get("PUBMED_API_KEY")
        or os.environ.get("NCBI_API_KEY", ""),
    }

    if request.method == "POST":
        form["source"] = (request.form.get("source") or form["source"]).strip()
        form["ai_provider"] = (request.form.get("ai_provider") or form["ai_provider"]).strip()
        form["query"] = (request.form.get("query") or "").strip()
        form["years"] = (request.form.get("years") or form["years"]).strip()
        form["max_results"] = (request.form.get("max_results") or form["max_results"]).strip()
        form["email"] = (request.form.get("email") or "").strip()
        form["api_key"] = (request.form.get("api_key") or "").strip()

        if not form["query"]:
            error = "请输入检索式。"
        else:
            try:
                years = int(form["years"])
            except ValueError:
                years = _get_default_years()
                form["years"] = str(years)

            try:
                max_results = int(form["max_results"])
            except ValueError:
                max_results = _get_default_max_results()
                form["max_results"] = str(max_results)

            try:
                bibtex_text, count, found_articles = _perform_search(
                    source_name=form["source"],
                    query=form["query"],
                    years=years,
                    max_results=max_results,
                    email=form["email"],
                    api_key=form["api_key"],
                    ai_provider=form["ai_provider"],
                )
                articles = [_build_view_article(info) for info in found_articles]
                if not count:
                    error = "没有检索到符合条件的文献。"
            except Exception as exc:  # pylint: disable=broad-except
                error = f"检索或生成 BibTeX 时出错：{exc}"

    return render_template(
        "index.html",
        form=form,
        error=error,
        bibtex_text=bibtex_text,
        count=count,
        articles=articles,
        sources=sources,
        ai_providers=ai_providers,
    )


@app.route("/download", methods=["POST"])
def download():
    """根据前端表单参数重新检索并返回 BibTeX 文件。"""
    query = (request.form.get("query") or "").strip()
    years_raw = (request.form.get("years") or "").strip()
    max_results_raw = (request.form.get("max_results") or "").strip()
    email = (request.form.get("email") or "").strip()
    api_key = (request.form.get("api_key") or "").strip()
    source_name = (request.form.get("source") or _default_source_name()).strip()
    ai_provider = (request.form.get("ai_provider") or _default_ai_provider_name()).strip()

    if not query:
        return "缺少检索式。", 400

    try:
        years = int(years_raw) if years_raw else _get_default_years()
    except ValueError:
        years = _get_default_years()

    try:
        max_results = int(max_results_raw) if max_results_raw else _get_default_max_results()
    except ValueError:
        max_results = _get_default_max_results()

    try:
        bibtex_text, count, _ = _perform_search(
            source_name=source_name,
            query=query,
            years=years,
            max_results=max_results,
            email=email,
            api_key=api_key,
            ai_provider=ai_provider,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"检索或生成 BibTeX 时出错：{exc}", 500

    if not count:
        return "没有检索到符合条件的文献。", 404

    filename = os.environ.get("PUBMED_OUTPUT") or "pubmed_results.bib"
    resp = Response(bibtex_text, mimetype="application/x-bibtex; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


if __name__ == "__main__":
    app.run(debug=True)
