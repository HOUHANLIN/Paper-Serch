import json
import os
from typing import List, Tuple

from flask import Flask, Response, render_template, request

from pubmed_bibtex import (
    _load_env,
    build_bibtex_entries,
    fetch_pubmed_details,
    search_pubmed,
)


app = Flask(__name__)

# 尝试从 .env 读取默认配置
_load_env()


def _get_default_years() -> int:
    years = os.environ.get("PUBMED_YEARS") or "5"
    try:
        return int(years)
    except ValueError:
        return 5


def _get_default_max_results() -> int:
    max_results = os.environ.get("PUBMED_MAX_RESULTS") or "10"
    try:
        return int(max_results)
    except ValueError:
        return 10


def _run_search(
    query: str,
    years: int,
    max_results: int,
    email: str,
    api_key: str,
) -> Tuple[str, int, List[dict]]:
    pmids = search_pubmed(
        query=query,
        years=years,
        max_results=max_results,
        email=email or None,
        api_key=api_key or None,
    )
    if not pmids:
        return "", 0, []

    xml_root = fetch_pubmed_details(
        pmids,
        email=email or None,
        api_key=api_key or None,
    )
    return build_bibtex_entries(xml_root)


@app.route("/", methods=["GET", "POST"])
def index():
    error = ""
    bibtex_text = ""
    count = 0
    articles: List[dict] = []

    # 表单初始值支持从环境变量读取
    form = {
        "query": os.environ.get("PUBMED_QUERY", ""),
        "years": str(_get_default_years()),
        "max_results": str(_get_default_max_results()),
        "email": os.environ.get("PUBMED_EMAIL", ""),
        "api_key": os.environ.get("PUBMED_API_KEY")
        or os.environ.get("NCBI_API_KEY", ""),
    }

    if request.method == "POST":
        form["query"] = (request.form.get("query") or "").strip()
        form["years"] = (request.form.get("years") or form["years"]).strip()
        form["max_results"] = (request.form.get("max_results") or form["max_results"]).strip()
        form["email"] = (request.form.get("email") or "").strip()
        form["api_key"] = (request.form.get("api_key") or "").strip()

        if not form["query"]:
            error = "请输入 PubMed 检索式。"
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
                bibtex_text, count, infos = _run_search(
                    query=form["query"],
                    years=years,
                    max_results=max_results,
                    email=form["email"],
                    api_key=form["api_key"],
                )
                # 将底层 info dict 转换为前端使用的精简结果
                for info in infos:
                    annote_raw = (info.get("annote") or "").strip()
                    summary_zh = ""
                    usage_zh = ""
                    if annote_raw:
                        try:
                            parsed = json.loads(annote_raw)
                            if isinstance(parsed, dict):
                                summary_zh = str(parsed.get("summary_zh") or "").strip()
                                usage_zh = str(parsed.get("usage_zh") or "").strip()
                        except Exception:
                            # annote 不是合法 JSON 时，前端只展示原始摘要
                            summary_zh = annote_raw

                    articles.append(
                        {
                            "title": info.get("title", "").strip() or "(无标题)",
                            "authors": info.get("authors", ""),
                            "journal": info.get("journal", ""),
                            "year": info.get("year", ""),
                            "abstract": info.get("abstract", ""),
                            "url": info.get("url", ""),
                            "pmid": info.get("pmid", ""),
                            "summary_zh": summary_zh,
                            "usage_zh": usage_zh,
                        }
                    )
                if not count:
                    error = "没有检索到符合条件的文献。"
            except Exception as exc:  # pylint: disable=broad-except
                error = f"检索或生成 BibTeX 时出错：{exc}"

    has_gemini = bool(
        os.environ.get("GEMINI_API_KEY") and os.environ.get("GEMINI_MODEL")
    )

    return render_template(
        "index.html",
        form=form,
        error=error,
        bibtex_text=bibtex_text,
        count=count,
        articles=articles,
        has_gemini=has_gemini,
    )


@app.route("/download", methods=["POST"])
def download():
    """根据前端表单参数重新检索并返回 BibTeX 文件。"""
    query = (request.form.get("query") or "").strip()
    years_raw = (request.form.get("years") or "").strip()
    max_results_raw = (request.form.get("max_results") or "").strip()
    email = (request.form.get("email") or "").strip()
    api_key = (request.form.get("api_key") or "").strip()

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
        bibtex_text, count, _ = _run_search(
            query=query,
            years=years,
            max_results=max_results,
            email=email,
            api_key=api_key,
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
    # 默认监听本地 5000 端口
    app.run(debug=True)
