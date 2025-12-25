from __future__ import annotations

import json
from typing import Dict, Generator, List, Tuple

from paper_sources import ArticleInfo
from paper_sources.registry import get_source

from services.ai_summary import apply_ai_summary, normalize_annote
from services.bibtex import build_bibtex_entries


def status_log_entry(step: str, status: str, detail: str) -> Dict[str, str]:
    return {"step": step, "status": status, "detail": detail}


def sse_message(event: str, data: Dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_view_article(info: ArticleInfo) -> Dict[str, str]:
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


def perform_search_stream(
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
        entry = status_log_entry(step, status, detail)
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

        yield {"type": "status", "entry": _emit("检索完成", "success", f"共获取 {len(articles)} 条候选文献")}

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
            status_log.append(status_log_entry("AI 摘要", "error", "AI 摘要失败，已返回未总结的结果"))

        view_articles = [build_view_article(info) for info in articles]
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


def consume_search_stream(resolved: Dict[str, object]) -> Tuple[str, str, int, List[Dict[str, str]], List[Dict[str, str]]]:
    error = ""
    bibtex_text = ""
    count = 0
    articles: List[Dict[str, str]] = []
    status_log: List[Dict[str, str]] = []

    for event in perform_search_stream(**resolved):
        if event.get("type") == "status" and event.get("entry"):
            status_log.append(event["entry"])
        if event.get("type") == "result":
            bibtex_text = str(event.get("bibtex_text") or "")
            count = int(event.get("count") or 0)
            articles = event.get("articles") or []
        if event.get("type") == "error" and event.get("message"):
            error = str(event.get("message"))
    return error, bibtex_text, count, articles, status_log


def prefix_status(direction: str, entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {
            "step": f"[{direction}] {entry.get('step', '')}",
            "status": entry.get("status", ""),
            "detail": entry.get("detail", ""),
        }
        for entry in entries
    ]

