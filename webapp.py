from typing import Dict, List

from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from ai_providers.registry import list_providers
from services.ai_query import generate_query_terms
from services.ai_models import list_gemini_models, list_ollama_models, list_openai_models
from services.directions import extract_search_directions
from paper_sources.registry import list_sources
from web_layer.forms import (
    default_ai_provider_name,
    default_source_name,
    get_source_defaults,
    parse_float,
    parse_int,
    resolve_form,
)
from web_layer.search import (
    consume_search_stream,
    perform_search_stream,
    prefix_status,
    sse_message,
    status_log_entry,
)

app = Flask(__name__)


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

    form, resolved = resolve_form(request.form if request.method == "POST" else {})

    if request.method == "POST":
        if not resolved["query"]:
            error = "请输入检索式。"
        else:
            try:
                error, bibtex_text, count, articles, status_log = consume_search_stream(resolved)
            except Exception as exc:  # pylint: disable=broad-except
                error = f"检索或生成 BibTeX 时出错：{exc}"
                status_log.append(status_log_entry("流程中断", "error", str(exc)))

    source_defaults = {source.name: get_source_defaults(source.name) for source in sources}

    return render_template(
        "index.html",
        current_page="index",
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
    form, _ = resolve_form({})
    source_defaults = {source.name: get_source_defaults(source.name) for source in sources}

    return render_template(
        "workflow.html",
        current_page="workflow",
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

    source = (request.form.get("source") or default_source_name()).strip()
    output_name = (request.form.get("output") or "").strip()
    if not output_name:
        output_name = str(get_source_defaults(source)["output"])
    filename = output_name
    resp = Response(bibtex_text, mimetype="application/x-bibtex; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@app.route("/api/generate_query", methods=["POST"])
def generate_query():
    data = request.get_json(force=True, silent=True) or {}
    intent = data.get("intent") or ""
    source = (data.get("source") or default_source_name()).strip()
    ai_provider = (data.get("ai_provider") or default_ai_provider_name()).strip()
    query, message = generate_query_terms(
        source_name=source,
        intent=intent,
        ai_provider=ai_provider,
        gemini_api_key=(data.get("gemini_api_key") or "").strip(),
        gemini_model=(data.get("gemini_model") or "").strip(),
        gemini_temperature=parse_float(data.get("gemini_temperature"), 0.0),
        openai_api_key=(data.get("openai_api_key") or "").strip(),
        openai_base_url=(data.get("openai_base_url") or "").strip(),
        openai_model=(data.get("openai_model") or "").strip(),
        openai_temperature=parse_float(data.get("openai_temperature"), 0.0),
        ollama_api_key=(data.get("ollama_api_key") or "").strip(),
        ollama_base_url=(data.get("ollama_base_url") or "").strip(),
        ollama_model=(data.get("ollama_model") or "").strip(),
        ollama_temperature=parse_float(data.get("ollama_temperature"), 0.0),
    )
    return jsonify({"query": query, "message": message})


@app.route("/api/list_models", methods=["POST"])
def list_models():
    data = request.get_json(force=True, silent=True) or {}
    provider = (data.get("provider") or data.get("ai_provider") or "").strip()
    if provider not in {"openai", "gemini", "ollama"}:
        return jsonify({"error": "不支持的 AI Provider", "models": []}), 400

    if provider == "openai":
        models, message = list_openai_models(
            api_key=(data.get("openai_api_key") or "").strip(),
            base_url=(data.get("openai_base_url") or "").strip(),
        )
    elif provider == "ollama":
        models, message = list_ollama_models(
            api_key=(data.get("ollama_api_key") or "").strip(),
            base_url=(data.get("ollama_base_url") or "").strip(),
        )
    else:
        models, message = list_gemini_models(api_key=(data.get("gemini_api_key") or "").strip())

    if not models:
        return jsonify({"error": message or "未获取到模型列表", "models": []}), 400
    return jsonify({"models": models, "message": message})


@app.route("/api/auto_workflow", methods=["POST"])
def auto_workflow():
    data = request.get_json(force=True, silent=True) or {}
    source = (data.get("source") or default_source_name()).strip()
    direction_ai_provider = (
        data.get("direction_ai_provider") or data.get("ai_provider") or default_ai_provider_name()
    ).strip()
    query_ai_provider = (data.get("query_ai_provider") or direction_ai_provider).strip()
    summary_ai_provider = (
        data.get("summary_ai_provider") or data.get("ai_provider") or default_ai_provider_name()
    ).strip()
    years = parse_int(data.get("years"), int(get_source_defaults(source)["years"]))
    desired_count = parse_int(data.get("direction_count"), 0)
    if desired_count <= 0:
        desired_count = None
    elif desired_count > 12:
        desired_count = 12
    max_results = max(
        1,
        parse_int(data.get("max_results_per_direction") or data.get("max_results"), 3),
    )

    directions, extraction_message = extract_search_directions(
        content=data.get("content") or "",
        ai_provider=direction_ai_provider,
        gemini_api_key=(data.get("gemini_api_key") or "").strip(),
        gemini_model=(data.get("gemini_model") or "").strip(),
        gemini_temperature=parse_float(data.get("gemini_temperature"), 0.0),
        openai_api_key=(data.get("openai_api_key") or "").strip(),
        openai_base_url=(data.get("openai_base_url") or "").strip(),
        openai_model=(data.get("openai_model") or "").strip(),
        openai_temperature=parse_float(data.get("openai_temperature"), 0.0),
        ollama_api_key=(data.get("ollama_api_key") or "").strip(),
        ollama_base_url=(data.get("ollama_base_url") or "").strip(),
        ollama_model=(data.get("ollama_model") or "").strip(),
        ollama_temperature=parse_float(data.get("ollama_temperature"), 0.0),
        desired_count=desired_count,
    )
    status_log: List[Dict[str, str]] = []
    if not directions:
        status_log.append(status_log_entry("提取方向", "error", extraction_message))
        return jsonify({"error": extraction_message, "status_log": status_log}), 400
    status_log.append(status_log_entry("提取方向", "success", extraction_message))

    direction_details: List[Dict[str, object]] = []

    max_query_retries = 3

    concurrency = parse_int(data.get("concurrency"), 3)
    if concurrency <= 0:
        concurrency = 1
    if concurrency > 6:
        concurrency = 6
    max_workers = min(concurrency, len(directions)) if directions else 1
    status_log.append(status_log_entry("并发检索", "success", f"方向数={len(directions)}，并发数={max_workers}"))

    def _run_direction(index: int, direction: str) -> Dict[str, object]:
        direction_status_log = [status_log_entry("检索方向", "running", direction)]
        try:
            query, query_message = generate_query_terms(
                source_name=source,
                intent=direction,
                ai_provider=query_ai_provider,
                gemini_api_key=(data.get("gemini_api_key") or "").strip(),
                gemini_model=(data.get("gemini_model") or "").strip(),
                gemini_temperature=parse_float(data.get("gemini_temperature"), 0.0),
                openai_api_key=(data.get("openai_api_key") or "").strip(),
                openai_base_url=(data.get("openai_base_url") or "").strip(),
                openai_model=(data.get("openai_model") or "").strip(),
                openai_temperature=parse_float(data.get("openai_temperature"), 0.0),
                ollama_api_key=(data.get("ollama_api_key") or "").strip(),
                ollama_base_url=(data.get("ollama_base_url") or "").strip(),
                ollama_model=(data.get("ollama_model") or "").strip(),
                ollama_temperature=parse_float(data.get("ollama_temperature"), 0.0),
            )

            if not query:
                direction_status_log.append(status_log_entry("生成检索式", "error", query_message))
                prefixed = prefix_status(direction, direction_status_log)
                return {
                    "index": index,
                    "direction": direction,
                    "detail": {
                        "direction": direction,
                        "query": "",
                        "message": query_message,
                        "error": query_message,
                        "status_log": prefixed,
                    },
                    "status_log": prefixed,
                    "bibtex_text": "",
                    "count": 0,
                    "articles": [],
                }

            direction_status_log.append(status_log_entry("生成检索式", "success", query_message))

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
                _, resolved = resolve_form(resolved_payload)
                if not summary_ai_provider:
                    resolved["ai_provider"] = ""
                search_error, bibtex_text, count, articles, search_status_log = consume_search_stream(resolved)
                direction_status_log.extend(search_status_log)

                if not search_error or count > 0:
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
                    status_log_entry("检索重试", "running", f"第 {retry_count} 次尝试改写检索式")
                )
                current_query, current_query_message = generate_query_terms(
                    source_name=source,
                    intent=retry_prompt,
                    ai_provider=query_ai_provider,
                    gemini_api_key=(data.get("gemini_api_key") or "").strip(),
                    gemini_model=(data.get("gemini_model") or "").strip(),
                    gemini_temperature=parse_float(data.get("gemini_temperature"), 0.0),
                    openai_api_key=(data.get("openai_api_key") or "").strip(),
                    openai_base_url=(data.get("openai_base_url") or "").strip(),
                    openai_model=(data.get("openai_model") or "").strip(),
                    openai_temperature=parse_float(data.get("openai_temperature"), 0.0),
                    ollama_api_key=(data.get("ollama_api_key") or "").strip(),
                    ollama_base_url=(data.get("ollama_base_url") or "").strip(),
                    ollama_model=(data.get("ollama_model") or "").strip(),
                    ollama_temperature=parse_float(data.get("ollama_temperature"), 0.0),
                )

                if not current_query:
                    direction_status_log.append(status_log_entry("检索重试", "error", current_query_message))
                    break

                direction_status_log.append(
                    status_log_entry("检索重试", "success", f"已生成新的检索式（重试 {retry_count}）")
                )

            prefixed = prefix_status(direction, direction_status_log)

            if search_error:
                return {
                    "index": index,
                    "direction": direction,
                    "detail": {
                        "direction": direction,
                        "query": current_query,
                        "message": current_query_message,
                        "error": search_error,
                        "retry_count": retry_count,
                        "status_log": prefixed,
                    },
                    "status_log": prefixed,
                    "bibtex_text": "",
                    "count": 0,
                    "articles": [],
                }

            for article in articles:
                article["direction"] = direction

            return {
                "index": index,
                "direction": direction,
                "detail": {
                    "direction": direction,
                    "query": current_query,
                    "message": current_query_message,
                    "count": count,
                    "articles": articles,
                    "bibtex_text": bibtex_text,
                    "retry_count": retry_count,
                    "status_log": prefixed,
                },
                "status_log": prefixed,
                "bibtex_text": bibtex_text,
                "count": count,
                "articles": articles,
            }
        except Exception as exc:  # pylint: disable=broad-except
            direction_status_log.append(status_log_entry("流程中断", "error", str(exc)))
            prefixed = prefix_status(direction, direction_status_log)
            return {
                "index": index,
                "direction": direction,
                "detail": {
                    "direction": direction,
                    "query": "",
                    "message": "",
                    "error": str(exc),
                    "status_log": prefixed,
                },
                "status_log": prefixed,
                "bibtex_text": "",
                "count": 0,
                "articles": [],
            }

    results: List[Dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run_direction, idx, direction) for idx, direction in enumerate(directions)]
        for fut in as_completed(futures):
            results.append(fut.result())

    results_sorted = sorted(results, key=lambda item: int(item.get("index") or 0))
    combined_bibtex_parts: List[str] = []
    combined_articles: List[Dict[str, str]] = []
    total_count = 0

    for item in results_sorted:
        direction_details.append(item.get("detail") or {})
        direction_status = item.get("status_log") or []
        if isinstance(direction_status, list):
            status_log.extend(direction_status)

        bibtex_text = str(item.get("bibtex_text") or "").strip()
        if bibtex_text:
            combined_bibtex_parts.append(bibtex_text)
        total_count += int(item.get("count") or 0)
        articles = item.get("articles") or []
        if isinstance(articles, list):
            combined_articles.extend(articles)

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
    _, resolved = resolve_form(form_data)

    def event_stream():
        for event in perform_search_stream(**resolved):
            event_type = str(event.get("type") or "message")
            payload = {k: v for k, v in event.items() if k != "type"}
            yield sse_message(event_type, payload)

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    return Response(stream_with_context(event_stream()), mimetype="text/event-stream", headers=headers)


@app.route("/tutorial", methods=["GET"])
def tutorial():
    sources = list_sources()
    ai_providers = list_providers()
    return render_template(
        "tutorial.html",
        current_page="tutorial",
        sources=sources,
        ai_providers=ai_providers,
    )


if __name__ == "__main__":
    app.run(debug=True)
