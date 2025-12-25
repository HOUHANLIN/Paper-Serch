from __future__ import annotations

import hashlib
import os
import queue
import secrets
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from pathlib import Path
from typing import Dict, List, Mapping

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

from app.ai.registry import list_providers
from app.core.ai_models import list_gemini_models, list_openai_models
from app.core.ai_query import generate_query_terms
from app.core.db import (
    adjust_credits,
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
    list_users_with_balances,
    set_user_admin,
)
from app.core.db import connect as db_connect
from app.core.directions import extract_search_directions
from app.core.env_loader import get_env_flag, load_env
from app.sources.registry import list_sources
from app.web.forms import (
    default_ai_provider_name,
    default_source_name,
    get_source_defaults,
    parse_float,
    parse_int,
    resolve_form,
)
from app.web.search import (
    consume_search_stream,
    perform_search_stream,
    prefix_status,
    sse_message,
    status_log_entry,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _initial_credits() -> int:
    try:
        return int(os.environ.get("INITIAL_CREDITS", "10"))
    except ValueError:
        return 10


def _ai_presets() -> Dict[str, str]:
    provider = (os.environ.get("PRESET_AI_PROVIDER") or default_ai_provider_name()).strip()
    return {
        "ai_provider": provider or default_ai_provider_name(),
        "openai_api_key": os.environ.get("OPENAI_API_KEY") or "",
        "openai_base_url": os.environ.get("OPENAI_BASE_URL") or "",
        "openai_model": os.environ.get("OPENAI_MODEL") or "",
        "openai_temperature": os.environ.get("OPENAI_TEMPERATURE") or "0",
        "gemini_api_key": os.environ.get("GEMINI_API_KEY") or "",
        "gemini_model": os.environ.get("GEMINI_MODEL") or "",
        "gemini_temperature": os.environ.get("GEMINI_TEMPERATURE") or "0",
    }


def _ai_preset_display() -> Dict[str, str]:
    presets = _ai_presets()
    provider = (presets.get("ai_provider") or default_ai_provider_name()).strip() or default_ai_provider_name()
    labels = {"openai": "OpenAI", "gemini": "Gemini"}
    model = presets.get(f"{provider}_model") or ""
    base_url = presets.get(f"{provider}_base_url") or ""
    return {
        "ai_provider": provider,
        "ai_provider_label": labels.get(provider, provider),
        "model": model,
        "base_url": base_url,
    }


def create_app() -> Flask:
    load_env(str(PROJECT_ROOT / ".env"))

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(16)
    init_db(default_db_path())

    allow_self_registration = get_env_flag("ALLOW_SELF_REGISTRATION", False)
    admin_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD") or ""

    def _allow_ai_config() -> bool:
        return bool(getattr(g, "current_user", None) and getattr(g.current_user, "is_admin", False))

    def _prepare_ai_payload(data: Mapping[str, str]) -> Dict[str, object]:
        presets = _ai_presets()
        allow_custom = _allow_ai_config()

        def pick(key: str) -> str:
            value = (data.get(key) or "").strip()
            if allow_custom and value:
                return value
            return str(presets.get(key) or "")

        payload = {
            "ai_provider": pick("ai_provider") or default_ai_provider_name(),
            "gemini_api_key": pick("gemini_api_key"),
            "gemini_model": pick("gemini_model"),
            "gemini_temperature": pick("gemini_temperature"),
            "openai_api_key": pick("openai_api_key"),
            "openai_base_url": pick("openai_base_url"),
            "openai_model": pick("openai_model"),
            "openai_temperature": pick("openai_temperature"),
        }
        payload["gemini_temperature"] = parse_float(payload["gemini_temperature"], 0.0)
        payload["openai_temperature"] = parse_float(payload["openai_temperature"], 0.0)
        return payload

    def _bootstrap_admin_from_env() -> None:
        if not admin_email or not admin_password:
            return
        conn = db_connect(default_db_path())
        try:
            existing = get_user_by_email(conn, admin_email)
            if existing:
                if not existing["is_admin"]:
                    set_user_admin(conn, int(existing["id"]), True)
                return
            password_hash = generate_password_hash(admin_password)
            create_user(
                conn,
                email=admin_email,
                password_hash=password_hash,
                initial_credits=_initial_credits(),
                is_admin=True,
            )
        finally:
            conn.close()

    _bootstrap_admin_from_env()

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
        g.is_admin = False
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
        g.is_admin = bool(user.is_admin)

    @app.context_processor
    def _inject_user():
        return {
            "current_user": getattr(g, "current_user", None),
            "credits_balance": getattr(g, "credits_balance", 0),
            "allow_ai_config": _allow_ai_config(),
            "ai_preset_display": _ai_preset_display(),
            "registration_open": allow_self_registration,
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

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if user is None:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "请先登录"}), 401
                next_url = request.full_path if request.query_string else request.path
                return redirect(url_for("login", next=next_url))
            if not getattr(user, "is_admin", False):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "需要管理员权限"}), 403
                return redirect(url_for("account"))
            return view(*args, **kwargs)

        return wrapped

    def _normalize_next_url(next_url: str) -> str:
        candidate = (next_url or "").strip()
        if not candidate:
            return ""
        if candidate.startswith("/") and not candidate.startswith("//") and not candidate.startswith("/\\"):
            return candidate
        return ""

    @app.route("/", methods=["GET", "POST"])
    def index():
        error = ""
        bibtex_text = ""
        count = 0
        articles: List[Dict[str, str]] = []
        status_log: List[Dict[str, str]] = []

        sources = list_sources()
        ai_providers = list_providers()
        allow_ai_customization = _allow_ai_config()
        ai_presets = _ai_presets()

        form, resolved = resolve_form(
            request.form if request.method == "POST" else {},
            allow_ai_customization=allow_ai_customization,
            preset_ai_config=ai_presets,
        )

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
        allow_ai_customization = _allow_ai_config()
        ai_presets = _ai_presets()
        form, _ = resolve_form({}, allow_ai_customization=allow_ai_customization, preset_ai_config=ai_presets)
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
        if not allow_self_registration:
            return (
                render_template(
                    "register.html",
                    current_page="register",
                    error="当前未开放自助注册，请联系管理员创建账号。",
                    next_url=next_url,
                    initial_credits=_initial_credits(),
                    registration_open=False,
                ),
                403 if request.method == "POST" else 200,
            )
        if request.method == "GET":
            return render_template(
                "register.html",
                current_page="register",
                error="",
                next_url=next_url,
                initial_credits=_initial_credits(),
                registration_open=True,
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
                    registration_open=True,
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
                    registration_open=True,
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
                    registration_open=True,
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
                    registration_open=True,
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

    @app.route("/admin/users", methods=["GET", "POST"])
    @admin_required
    def admin_users():
        error = ""
        message = ""
        conn = _get_db()
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "create":
                email = (request.form.get("email") or "").strip().lower()
                password = request.form.get("password") or ""
                initial_credits = parse_int(request.form.get("initial_credits"), _initial_credits())
                make_admin = (request.form.get("is_admin") or "") == "1"
                if not email or "@" not in email:
                    error = "请输入合法邮箱。"
                elif not password or len(password) < 6:
                    error = "密码至少 6 位。"
                else:
                    try:
                        password_hash = generate_password_hash(password)
                        create_user(
                            conn,
                            email=email,
                            password_hash=password_hash,
                            initial_credits=initial_credits,
                            is_admin=make_admin,
                        )
                        message = f"已创建账号 {email}（{'管理员' if make_admin else '普通用户'}），初始余额 {initial_credits}。"
                    except sqlite3.IntegrityError:
                        error = "该邮箱已存在，请勿重复创建。"
                    except Exception as exc:  # pylint: disable=broad-except
                        error = f"创建失败：{exc}"
            elif action == "adjust":
                target_id = parse_int(request.form.get("user_id"), 0)
                delta = parse_int(request.form.get("delta"), 0)
                reason = (request.form.get("reason") or "admin_adjustment").strip()
                target = get_user_by_id(conn, target_id)
                if not target:
                    error = "用户不存在。"
                else:
                    try:
                        new_balance = adjust_credits(
                            conn,
                            user_id=target_id,
                            delta=delta,
                            reason=reason or "admin_adjustment",
                            actor_user_id=g.current_user.id,
                        )
                        message = f"已为 {target.email} 调整余额 {delta}，当前余额 {new_balance}。"
                    except Exception as exc:  # pylint: disable=broad-except
                        error = f"调整失败：{exc}"
            elif action == "toggle_admin":
                target_id = parse_int(request.form.get("user_id"), 0)
                make_admin = (request.form.get("make_admin") or "") == "1"
                target = get_user_by_id(conn, target_id)
                if not target:
                    error = "用户不存在。"
                elif target_id == g.current_user.id and not make_admin:
                    error = "无法移除自己的管理员权限。"
                else:
                    set_user_admin(conn, target_id, make_admin)
                    message = f"已更新 {target.email} 的管理员状态为 {'是' if make_admin else '否'}。"
            else:
                error = "未知操作类型。"

        users = list_users_with_balances(conn)
        return render_template(
            "admin_users.html",
            current_page="admin_users",
            users=users,
            error=error,
            message=message,
            initial_credits=_initial_credits(),
        )

    @app.route("/download", methods=["POST"])
    def download():
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
        ai_payload = _prepare_ai_payload(data)
        ai_provider = (ai_payload.get("ai_provider") or default_ai_provider_name()).strip()
        query, message = generate_query_terms(
            source_name=source,
            intent=intent,
            ai_provider=ai_provider,
            gemini_api_key=str(ai_payload.get("gemini_api_key") or ""),
            gemini_model=str(ai_payload.get("gemini_model") or ""),
            gemini_temperature=float(ai_payload.get("gemini_temperature") or 0.0),
            openai_api_key=str(ai_payload.get("openai_api_key") or ""),
            openai_base_url=str(ai_payload.get("openai_base_url") or ""),
            openai_model=str(ai_payload.get("openai_model") or ""),
            openai_temperature=float(ai_payload.get("openai_temperature") or 0.0),
        )
        return jsonify({"query": query, "message": message})

    @app.route("/api/list_models", methods=["POST"])
    def list_models():
        if not _allow_ai_config():
            return jsonify({"error": "仅管理员可获取模型列表", "models": []}), 403
        data = request.get_json(force=True, silent=True) or {}
        ai_payload = _prepare_ai_payload(data)
        provider = (data.get("provider") or data.get("ai_provider") or "").strip()
        if not provider:
            provider = str(ai_payload.get("ai_provider") or "").strip()
        if provider not in {"openai", "gemini"}:
            return jsonify({"error": "不支持的 AI Provider", "models": []}), 400

        if provider == "openai":
            models, message = list_openai_models(
                api_key=str(ai_payload.get("openai_api_key") or "").strip(),
                base_url=str(ai_payload.get("openai_base_url") or "").strip(),
            )
        else:
            models, message = list_gemini_models(api_key=str(ai_payload.get("gemini_api_key") or "").strip())

        if not models:
            return jsonify({"error": message or "未获取到模型列表", "models": []}), 400
        return jsonify({"models": models, "message": message})

    @app.route("/api/auto_workflow", methods=["POST"])
    @login_required
    def auto_workflow():
        data = request.get_json(force=True, silent=True) or {}
        source = (data.get("source") or default_source_name()).strip()
        ai_payload = _prepare_ai_payload(data)
        default_provider = str(ai_payload.get("ai_provider") or default_ai_provider_name())
        direction_ai_provider = (data.get("direction_ai_provider") or data.get("ai_provider") or default_provider).strip()
        query_ai_provider = (data.get("query_ai_provider") or direction_ai_provider or default_provider).strip()
        summary_ai_provider = (data.get("summary_ai_provider") or data.get("ai_provider") or default_provider).strip()
        if not _allow_ai_config():
            direction_ai_provider = query_ai_provider = summary_ai_provider = default_provider
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
            gemini_api_key=str(ai_payload.get("gemini_api_key") or ""),
            gemini_model=str(ai_payload.get("gemini_model") or ""),
            gemini_temperature=float(ai_payload.get("gemini_temperature") or 0.0),
            openai_api_key=str(ai_payload.get("openai_api_key") or ""),
            openai_base_url=str(ai_payload.get("openai_base_url") or ""),
            openai_model=str(ai_payload.get("openai_model") or ""),
            openai_temperature=float(ai_payload.get("openai_temperature") or 0.0),
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
                    gemini_api_key=str(ai_payload.get("gemini_api_key") or ""),
                    gemini_model=str(ai_payload.get("gemini_model") or ""),
                    gemini_temperature=float(ai_payload.get("gemini_temperature") or 0.0),
                    openai_api_key=str(ai_payload.get("openai_api_key") or ""),
                    openai_base_url=str(ai_payload.get("openai_base_url") or ""),
                    openai_model=str(ai_payload.get("openai_model") or ""),
                    openai_temperature=float(ai_payload.get("openai_temperature") or 0.0),
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
                        "gemini_api_key": str(ai_payload.get("gemini_api_key") or ""),
                        "gemini_model": str(ai_payload.get("gemini_model") or ""),
                        "gemini_temperature": ai_payload.get("gemini_temperature") or "0",
                        "openai_api_key": str(ai_payload.get("openai_api_key") or ""),
                        "openai_base_url": str(ai_payload.get("openai_base_url") or ""),
                        "openai_model": str(ai_payload.get("openai_model") or ""),
                        "openai_temperature": ai_payload.get("openai_temperature") or "0",
                    }
                    _, resolved = resolve_form(
                        resolved_payload,
                        allow_ai_customization=_allow_ai_config(),
                        preset_ai_config=_ai_presets(),
                    )
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
                        gemini_api_key=str(ai_payload.get("gemini_api_key") or ""),
                        gemini_model=str(ai_payload.get("gemini_model") or ""),
                        gemini_temperature=float(ai_payload.get("gemini_temperature") or 0.0),
                        openai_api_key=str(ai_payload.get("openai_api_key") or ""),
                        openai_base_url=str(ai_payload.get("openai_base_url") or ""),
                        openai_model=str(ai_payload.get("openai_model") or ""),
                        openai_temperature=float(ai_payload.get("openai_temperature") or 0.0),
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
        ai_payload = _prepare_ai_payload(data)
        default_provider = str(ai_payload.get("ai_provider") or default_ai_provider_name())
        direction_ai_provider = (data.get("direction_ai_provider") or data.get("ai_provider") or default_provider).strip()
        query_ai_provider = (data.get("query_ai_provider") or direction_ai_provider or default_provider).strip()
        summary_ai_provider = (data.get("summary_ai_provider") or data.get("ai_provider") or default_provider).strip()
        if not _allow_ai_config():
            direction_ai_provider = query_ai_provider = summary_ai_provider = default_provider
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
                    gemini_api_key=str(ai_payload.get("gemini_api_key") or ""),
                    gemini_model=str(ai_payload.get("gemini_model") or ""),
                    gemini_temperature=float(ai_payload.get("gemini_temperature") or 0.0),
                    openai_api_key=str(ai_payload.get("openai_api_key") or ""),
                    openai_base_url=str(ai_payload.get("openai_base_url") or ""),
                    openai_model=str(ai_payload.get("openai_model") or ""),
                    openai_temperature=float(ai_payload.get("openai_temperature") or 0.0),
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
                            gemini_api_key=str(ai_payload.get("gemini_api_key") or ""),
                            gemini_model=str(ai_payload.get("gemini_model") or ""),
                            gemini_temperature=float(ai_payload.get("gemini_temperature") or 0.0),
                            openai_api_key=str(ai_payload.get("openai_api_key") or ""),
                            openai_base_url=str(ai_payload.get("openai_base_url") or ""),
                            openai_model=str(ai_payload.get("openai_model") or ""),
                            openai_temperature=float(ai_payload.get("openai_temperature") or 0.0),
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
                                "gemini_api_key": str(ai_payload.get("gemini_api_key") or ""),
                                "gemini_model": str(ai_payload.get("gemini_model") or ""),
                                "gemini_temperature": ai_payload.get("gemini_temperature") or "0",
                                "openai_api_key": str(ai_payload.get("openai_api_key") or ""),
                                "openai_base_url": str(ai_payload.get("openai_base_url") or ""),
                                "openai_model": str(ai_payload.get("openai_model") or ""),
                                "openai_temperature": ai_payload.get("openai_temperature") or "0",
                            }
                            _, resolved = resolve_form(
                                resolved_payload,
                                allow_ai_customization=_allow_ai_config(),
                                preset_ai_config=_ai_presets(),
                            )
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
                                gemini_api_key=str(ai_payload.get("gemini_api_key") or ""),
                                gemini_model=str(ai_payload.get("gemini_model") or ""),
                                gemini_temperature=float(ai_payload.get("gemini_temperature") or 0.0),
                                openai_api_key=str(ai_payload.get("openai_api_key") or ""),
                                openai_base_url=str(ai_payload.get("openai_base_url") or ""),
                                openai_model=str(ai_payload.get("openai_model") or ""),
                                openai_temperature=float(ai_payload.get("openai_temperature") or 0.0),
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
        _, resolved = resolve_form(
            form_data,
            allow_ai_customization=_allow_ai_config(),
            preset_ai_config=_ai_presets(),
        )

        def event_stream():
            for event in perform_search_stream(**resolved):
                event_type = str(event.get("type") or "message")
                payload = {k: v for k, v in event.items() if k != "type"}
                yield sse_message(event_type, payload)

        headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
        return Response(stream_with_context(event_stream()), mimetype="text/event-stream", headers=headers)

    return app


app = create_app()


if __name__ == "__main__":
    init_db(default_db_path())
    app.run(debug=True)
