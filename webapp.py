from typing import Dict, List
import hashlib
import queue
import threading
import os
import secrets
import sqlite3
import uuid
from functools import wraps

from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import (
    Flask,
    Response,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from ai_providers.registry import list_providers
from services.ai_query import generate_query_terms
from services.ai_models import list_gemini_models, list_ollama_models, list_openai_models
from services.directions import extract_search_directions
from paper_sources.registry import list_sources
from services.db import (
    consume_one_workflow_credit,
    create_user,
    default_db_path,
    finish_workflow_run,
    get_credits,
    get_user_by_email,
    get_user_by_id,
    init_db,
    insert_workflow_run,
    list_recent_ledger,
)
from services.db import connect as db_connect
from services.env_loader import load_env
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

load_env()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(16)
init_db(default_db_path())


def _initial_credits() -> int:
    try:
        return int(os.environ.get("INITIAL_CREDITS", "10"))
    except ValueError:
        return 10


def _get_db():
    if "db" not in g:
        g.db = db_connect(default_db_path())
    return g.db


@app.teardown_appcontext
def _close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.before_request
def _load_user():
    user_id = session.get("user_id")
    g.current_user = None
    g.credits_balance = 0
    if user_id is None:
        return
    try:
        user = get_user_by_id(_get_db(), int(user_id))
    except Exception:
        user = None
    if user is None:
        session.pop("user_id", None)
        return
    g.current_user = user
    g.credits_balance = get_credits(_get_db(), user.id)


@app.context_processor
def _inject_user():
    return {
        "current_user": getattr(g, "current_user", None),
        "credits_balance": getattr(g, "credits_balance", 0),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "请先登录"}), 401
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=next_url))
        return view(*args, **kwargs)

    return wrapped


def _normalize_next_url(next_url: str) -> str:
    candidate = (next_url or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("/") and not candidate.startswith("//") and not candidate.startswith("/\\"):
        return candidate
    return ""


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
@login_required
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


@app.route("/register", methods=["GET", "POST"])
def register():
    next_url = _normalize_next_url(request.args.get("next") or request.form.get("next") or "")
    if request.method == "GET":
        return render_template(
            "register.html",
            current_page="register",
            error="",
            next_url=next_url,
            initial_credits=_initial_credits(),
        )

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""
    if not email or "@" not in email:
        return (
            render_template(
                "register.html",
                current_page="register",
                error="请输入合法邮箱。",
                next_url=next_url,
                initial_credits=_initial_credits(),
            ),
            400,
        )
    if not password or len(password) < 6:
        return (
            render_template(
                "register.html",
                current_page="register",
                error="密码至少 6 位。",
                next_url=next_url,
                initial_credits=_initial_credits(),
            ),
            400,
        )
    if password != password2:
        return (
            render_template(
                "register.html",
                current_page="register",
                error="两次输入的密码不一致。",
                next_url=next_url,
                initial_credits=_initial_credits(),
            ),
            400,
        )

    password_hash = generate_password_hash(password)
    try:
        user = create_user(_get_db(), email=email, password_hash=password_hash, initial_credits=_initial_credits())
    except sqlite3.IntegrityError:
        return (
            render_template(
                "register.html",
                current_page="register",
                error="该邮箱已注册，请直接登录。",
                next_url=next_url,
                initial_credits=_initial_credits(),
            ),
            400,
        )

    session["user_id"] = user.id
    return redirect(next_url or url_for("account"))


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = _normalize_next_url(request.args.get("next") or request.form.get("next") or "")
    if request.method == "GET":
        return render_template("login.html", current_page="login", error="", next_url=next_url)

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    if not email or not password:
        return render_template("login.html", current_page="login", error="请输入邮箱和密码。", next_url=next_url), 400

    row = get_user_by_email(_get_db(), email)
    if not row or not check_password_hash(str(row["password_hash"]), password):
        return render_template("login.html", current_page="login", error="邮箱或密码错误。", next_url=next_url), 400

    session["user_id"] = int(row["id"])
    return redirect(next_url or url_for("account"))


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return redirect(url_for("index"))


@app.route("/account", methods=["GET"])
@login_required
def account():
    ledger = list_recent_ledger(_get_db(), g.current_user.id, limit=20)
    return render_template("account.html", current_page="account", ledger=ledger)


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
@login_required
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

    pubmed_concurrency = parse_int(data.get("concurrency"), 3)
    if pubmed_concurrency <= 0:
        pubmed_concurrency = 1

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

    run_id = str(uuid.uuid4())
    input_hash = hashlib.sha256((data.get("content") or "").encode("utf-8")).hexdigest()
    config_snapshot = {
        "source": source,
        "years": years,
        "direction_ai_provider": direction_ai_provider,
        "query_ai_provider": query_ai_provider,
        "summary_ai_provider": summary_ai_provider,
        "direction_count": desired_count or "",
        "max_results_per_direction": max_results,
        "pubmed_concurrency": pubmed_concurrency,
        "directions": directions,
    }
    insert_workflow_run(
        _get_db(),
        run_id=run_id,
        user_id=g.current_user.id,
        status="running",
        config=config_snapshot,
        input_hash=input_hash,
    )
    try:
        consume_one_workflow_credit(
            _get_db(),
            user_id=g.current_user.id,
            run_id=run_id,
            idempotency_key=f"workflow:{run_id}:consume",
        )
    except Exception as exc:  # pylint: disable=broad-except
        finish_workflow_run(_get_db(), run_id=run_id, status="failed", error_message=str(exc))
        status_log.append(status_log_entry("扣费", "error", str(exc)))
        return jsonify({"error": str(exc), "status_log": status_log, "run_id": run_id}), 402

    direction_details: List[Dict[str, object]] = []

    max_query_retries = 3

    pubmed_semaphore = threading.BoundedSemaphore(pubmed_concurrency)

    max_workers = len(directions) if directions else 1
    status_log.append(
        status_log_entry(
            "并发检索",
            "success",
            f"方向数={len(directions)}（不限制方向并发），PubMed 并发={pubmed_concurrency}",
        )
    )

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
                resolved["pubmed_semaphore"] = pubmed_semaphore
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

    try:
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
        finish_workflow_run(_get_db(), run_id=run_id, status="succeeded")
        return jsonify(
            {
                "run_id": run_id,
                "directions": direction_details,
                "status_log": status_log,
                "bibtex_text": combined_bibtex,
                "count": total_count,
                "articles": combined_articles,
                "message": extraction_message,
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        finish_workflow_run(_get_db(), run_id=run_id, status="failed", error_message=str(exc))
        status_log.append(status_log_entry("自动工作流", "error", str(exc)))
        return jsonify({"error": str(exc), "status_log": status_log, "run_id": run_id}), 500


@app.route("/api/auto_workflow_stream", methods=["POST"])
@login_required
def auto_workflow_stream():
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

    pubmed_concurrency = parse_int(data.get("concurrency"), 3)
    if pubmed_concurrency <= 0:
        pubmed_concurrency = 1
    pubmed_semaphore = threading.BoundedSemaphore(pubmed_concurrency)

    def event_stream():
        run_id = ""
        try:
            yield sse_message(
                "status",
                {"entry": status_log_entry("自动工作流", "running", "正在拆解内容方向...")},
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
            if not directions:
                yield sse_message("status", {"entry": status_log_entry("提取方向", "error", extraction_message)})
                yield sse_message("error", {"message": extraction_message})
                return

            run_id = str(uuid.uuid4())
            input_hash = hashlib.sha256((data.get("content") or "").encode("utf-8")).hexdigest()
            config_snapshot = {
                "source": source,
                "years": years,
                "direction_ai_provider": direction_ai_provider,
                "query_ai_provider": query_ai_provider,
                "summary_ai_provider": summary_ai_provider,
                "direction_count": desired_count or "",
                "max_results_per_direction": max_results,
                "pubmed_concurrency": pubmed_concurrency,
                "directions": directions,
            }
            insert_workflow_run(
                _get_db(),
                run_id=run_id,
                user_id=g.current_user.id,
                status="running",
                config=config_snapshot,
                input_hash=input_hash,
            )
            consume_one_workflow_credit(
                _get_db(),
                user_id=g.current_user.id,
                run_id=run_id,
                idempotency_key=f"workflow:{run_id}:consume",
            )

            max_workers = len(directions) if directions else 1
            yield sse_message("status", {"entry": status_log_entry("提取方向", "success", extraction_message)})
            yield sse_message(
                "status",
                {
                    "entry": status_log_entry(
                        "并发检索",
                        "success",
                        f"方向数={len(directions)}（不限制方向并发），PubMed 并发={pubmed_concurrency}",
                    )
                },
            )
            yield sse_message(
                "workflow_init",
                {"run_id": run_id, "directions": directions, "message": extraction_message},
            )

            event_queue: queue.Queue[tuple[str, Dict[str, object]]] = queue.Queue()
            max_query_retries = 3

            def _emit(event_type: str, payload: Dict[str, object]) -> None:
                event_queue.put((event_type, payload))

            def _prefixed(direction: str, entry: Dict[str, str]) -> Dict[str, str]:
                return {
                    "step": f"[{direction}] {entry.get('step', '')}",
                    "status": entry.get("status", ""),
                    "detail": entry.get("detail", ""),
                }

            def _run_direction(index: int, direction: str) -> None:
                direction_status_log: List[Dict[str, str]] = [status_log_entry("检索方向", "running", direction)]
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
                        for entry in prefix_status(direction, direction_status_log):
                            _emit("status", {"entry": entry})
                        _emit(
                            "direction_result",
                            {
                                "index": index,
                                "detail": {
                                    "direction": direction,
                                    "query": "",
                                    "message": query_message,
                                    "error": query_message,
                                    "status_log": prefix_status(direction, direction_status_log),
                                },
                            },
                        )
                        return

                    direction_status_log.append(status_log_entry("生成检索式", "success", query_message))
                    _emit("status", {"entry": _prefixed(direction, direction_status_log[-1])})

                    current_query = query
                    current_query_message = query_message
                    retry_count = 0
                    bibtex_text = ""
                    count = 0
                    view_articles: List[Dict[str, str]] = []
                    search_error = ""

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
                        resolved["pubmed_semaphore"] = pubmed_semaphore

                        for event in perform_search_stream(**resolved):
                            if event.get("type") == "status" and event.get("entry"):
                                _emit("status", {"entry": _prefixed(direction, event["entry"])})
                            if event.get("type") == "result":
                                bibtex_text = str(event.get("bibtex_text") or "")
                                count = int(event.get("count") or 0)
                                view_articles = event.get("articles") or []
                            if event.get("type") == "error" and event.get("message"):
                                search_error = str(event.get("message"))

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
                        _emit(
                            "status",
                            {
                                "entry": _prefixed(
                                    direction,
                                    status_log_entry("检索重试", "running", f"第 {retry_count} 次尝试改写检索式"),
                                )
                            },
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
                            _emit(
                                "status",
                                {
                                    "entry": _prefixed(
                                        direction,
                                        status_log_entry("检索重试", "error", current_query_message),
                                    )
                                },
                            )
                            break
                        _emit(
                            "status",
                            {
                                "entry": _prefixed(
                                    direction,
                                    status_log_entry(
                                        "检索重试",
                                        "success",
                                        f"已生成新的检索式（重试 {retry_count}）",
                                    ),
                                )
                            },
                        )
                        search_error = ""
                        bibtex_text = ""
                        count = 0
                        view_articles = []

                    for article in view_articles:
                        article["direction"] = direction

                    if search_error:
                        _emit(
                            "direction_result",
                            {
                                "index": index,
                                "detail": {
                                    "direction": direction,
                                    "query": current_query,
                                    "message": current_query_message,
                                    "error": search_error,
                                    "retry_count": retry_count,
                                    "status_log": [],
                                },
                            },
                        )
                        return

                    _emit(
                        "direction_result",
                        {
                            "index": index,
                            "detail": {
                                "direction": direction,
                                "query": current_query,
                                "message": current_query_message,
                                "count": count,
                                "articles": view_articles,
                                "bibtex_text": bibtex_text,
                                "retry_count": retry_count,
                                "status_log": [],
                            },
                        },
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    _emit(
                        "direction_result",
                        {
                            "index": index,
                            "detail": {
                                "direction": direction,
                                "query": "",
                                "message": "",
                                "error": str(exc),
                                "status_log": [],
                            },
                        },
                    )

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for idx, direction in enumerate(directions):
                    executor.submit(_run_direction, idx, direction)

                direction_details: List[Dict[str, object]] = [{} for _ in directions]
                combined_bibtex_parts: List[str] = []
                combined_articles: List[Dict[str, str]] = []
                total_count = 0
                finished = 0

                while finished < len(directions):
                    event_type, payload = event_queue.get()
                    if event_type == "direction_result":
                        idx = int(payload.get("index") or 0)
                        detail = payload.get("detail") or {}
                        if 0 <= idx < len(direction_details):
                            direction_details[idx] = detail

                        detail_error = str(detail.get("error") or "").strip()
                        if not detail_error:
                            bibtex_text = str(detail.get("bibtex_text") or "").strip()
                            if bibtex_text:
                                combined_bibtex_parts.append(bibtex_text)
                            total_count += int(detail.get("count") or 0)
                            articles = detail.get("articles") or []
                            if isinstance(articles, list):
                                combined_articles.extend(articles)

                        finished += 1
                        yield sse_message("direction_result", payload)
                    else:
                        yield sse_message(event_type, payload)

                combined_bibtex = "\n\n".join(part.strip() for part in combined_bibtex_parts if part.strip())
                yield sse_message(
                    "workflow_done",
                    {
                        "run_id": run_id,
                        "directions": direction_details,
                        "bibtex_text": combined_bibtex,
                        "count": total_count,
                        "articles": combined_articles,
                        "message": extraction_message,
                    },
                )
            finish_workflow_run(_get_db(), run_id=run_id, status="succeeded")
        except Exception as exc:  # pylint: disable=broad-except
            if run_id:
                finish_workflow_run(_get_db(), run_id=run_id, status="failed", error_message=str(exc))
            yield sse_message("status", {"entry": status_log_entry("自动工作流", "error", str(exc))})
            yield sse_message("error", {"message": str(exc)})
            return

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    return Response(stream_with_context(event_stream()), mimetype="text/event-stream", headers=headers)


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
    init_db(default_db_path())
    app.run(debug=True)
