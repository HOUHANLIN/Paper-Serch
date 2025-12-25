from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_db_path() -> str:
    return os.environ.get("PAPER_SERCH_DB_PATH") or os.environ.get("DATABASE_PATH") or "paper_serch.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  ai_provider TEXT NOT NULL DEFAULT '',
  ai_model TEXT NOT NULL DEFAULT '',
  ai_api_key TEXT NOT NULL DEFAULT '',
  ai_base_url TEXT NOT NULL DEFAULT '',
  workflow_max_directions INTEGER NOT NULL DEFAULT 6,
  workflow_max_results_per_direction INTEGER NOT NULL DEFAULT 3,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  user_id INTEGER PRIMARY KEY,
  credits_balance INTEGER NOT NULL DEFAULT 0,
  credits_unlimited INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS workflow_runs (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  input_hash TEXT,
  config_json TEXT,
  error_message TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS credit_ledger (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  workflow_run_id TEXT,
  entry_type TEXT NOT NULL,
  units INTEGER NOT NULL,
  reason TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  metadata_json TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_workflow_once
  ON credit_ledger(workflow_run_id, reason)
  WHERE workflow_run_id IS NOT NULL AND reason = 'workflow_consumption';
"""


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        _ensure_admin_column(conn)
        _ensure_users_ai_columns(conn)
        _ensure_users_ai_secret_columns(conn)
        _ensure_users_workflow_limit_columns(conn)
        _ensure_accounts_unlimited_column(conn)
        _backfill_admin_unlimited(conn)
        _backfill_workflow_limit_defaults(conn)
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise


@dataclass(frozen=True)
class User:
    id: int
    email: str
    is_admin: bool
    ai_provider: str
    ai_model: str
    ai_api_key: str
    ai_base_url: str
    workflow_max_directions: int
    workflow_max_results_per_direction: int
    created_at: str


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[User]:
    row = conn.execute(
        "SELECT id, email, is_admin, ai_provider, ai_model, ai_api_key, ai_base_url, workflow_max_directions, "
        "workflow_max_results_per_direction, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return User(
        id=int(row["id"]),
        email=str(row["email"]),
        is_admin=bool(row["is_admin"]),
        ai_provider=str(row["ai_provider"] or ""),
        ai_model=str(row["ai_model"] or ""),
        ai_api_key=str(row["ai_api_key"] or ""),
        ai_base_url=str(row["ai_base_url"] or ""),
        workflow_max_directions=int(row["workflow_max_directions"] or 6),
        workflow_max_results_per_direction=int(row["workflow_max_results_per_direction"] or 3),
        created_at=str(row["created_at"]),
    )


def get_user_by_email(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()


def create_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    password_hash: str,
    initial_credits: int,
    is_admin: bool = False,
    ai_provider: str = "",
    ai_model: str = "",
    ai_api_key: str = "",
    ai_base_url: str = "",
) -> User:
    email_clean = email.strip().lower()
    now = utc_now_iso()
    provider = (ai_provider or "").strip()
    model = (ai_model or "").strip()
    api_key = (ai_api_key or "").strip()
    base_url = (ai_base_url or "").strip()
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, is_admin, ai_provider, ai_model, ai_api_key, ai_base_url, "
            "workflow_max_directions, workflow_max_results_per_direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email_clean,
                password_hash,
                1 if is_admin else 0,
                provider,
                model,
                api_key,
                base_url,
                6,
                3,
                now,
            ),
        )
        user_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO accounts(user_id, credits_balance, credits_unlimited, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, int(initial_credits if not is_admin else 0), 1 if is_admin else 0, now),
        )
    user = get_user_by_id(conn, user_id)
    if not user:
        raise RuntimeError("创建用户失败")
    return user


def get_credits(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute("SELECT credits_balance FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return 0
    return int(row["credits_balance"] or 0)


def is_credits_unlimited(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute(
        "SELECT COALESCE(credits_unlimited, 0) AS credits_unlimited FROM accounts WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return bool(row and int(row["credits_unlimited"] or 0))


def get_user_ai_config(conn: sqlite3.Connection, user_id: int) -> Dict[str, str]:
    row = conn.execute(
        "SELECT ai_provider, ai_model, ai_api_key, ai_base_url FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return {"ai_provider": "", "ai_model": "", "ai_api_key": "", "ai_base_url": ""}
    return {
        "ai_provider": str(row["ai_provider"] or ""),
        "ai_model": str(row["ai_model"] or ""),
        "ai_api_key": str(row["ai_api_key"] or ""),
        "ai_base_url": str(row["ai_base_url"] or ""),
    }


def set_user_ai_config(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    ai_provider: str,
    ai_model: str,
    ai_api_key: str,
    ai_base_url: str,
) -> None:
    provider = (ai_provider or "").strip()
    model = (ai_model or "").strip()
    api_key = (ai_api_key or "").strip()
    base_url = (ai_base_url or "").strip()
    if provider and provider not in {"openai", "gemini"}:
        raise ValueError("不支持的 AI Provider")
    conn.execute(
        "UPDATE users SET ai_provider = ?, ai_model = ?, ai_api_key = ?, ai_base_url = ? WHERE id = ?",
        (provider, model, api_key, base_url, user_id),
    )


def set_user_workflow_limits(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    workflow_max_directions: int,
    workflow_max_results_per_direction: int,
) -> None:
    max_dirs = int(workflow_max_directions)
    max_results = int(workflow_max_results_per_direction)
    if max_dirs < 1 or max_dirs > 12:
        raise ValueError("方向数量上限必须在 1-12 之间")
    if max_results < 1 or max_results > 50:
        raise ValueError("每方向文献上限必须在 1-50 之间")
    conn.execute(
        "UPDATE users SET workflow_max_directions = ?, workflow_max_results_per_direction = ? WHERE id = ?",
        (max_dirs, max_results, user_id),
    )


def insert_workflow_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    user_id: int,
    status: str,
    config: Dict[str, Any],
    input_hash: str = "",
) -> None:
    now = utc_now_iso()
    conn.execute(
        "INSERT INTO workflow_runs(id, user_id, status, created_at, started_at, input_hash, config_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, user_id, status, now, now if status == "running" else None, input_hash, json.dumps(config, ensure_ascii=False)),
    )


def finish_workflow_run(conn: sqlite3.Connection, *, run_id: str, status: str, error_message: str = "") -> None:
    now = utc_now_iso()
    conn.execute(
        "UPDATE workflow_runs SET status = ?, finished_at = ?, error_message = ? WHERE id = ?",
        (status, now, (error_message or "")[:500], run_id),
    )


def consume_one_workflow_credit(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    run_id: str,
    idempotency_key: str,
) -> None:
    now = utc_now_iso()
    with transaction(conn):
        if idempotency_key:
            exists = conn.execute(
                "SELECT 1 FROM credit_ledger WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if exists:
                return

        unlimited = is_credits_unlimited(conn, user_id)
        row = conn.execute(
            "SELECT credits_balance FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        balance = int(row["credits_balance"] or 0) if row else 0
        if not unlimited and balance < 1:
            raise RuntimeError("余额不足：请先充值或联系管理员增加次数")

        if not unlimited:
            conn.execute(
                "UPDATE accounts SET credits_balance = credits_balance - 1, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
        conn.execute(
            "INSERT INTO credit_ledger(id, user_id, workflow_run_id, entry_type, units, reason, idempotency_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                user_id,
                run_id,
                "debit" if not unlimited else "info",
                1 if not unlimited else 0,
                "workflow_consumption",
                idempotency_key,
                now,
            ),
        )


def list_recent_ledger(conn: sqlite3.Connection, user_id: int, limit: int = 20) -> Iterable[sqlite3.Row]:
    return conn.execute(
        "SELECT created_at, entry_type, units, reason, workflow_run_id "
        "FROM credit_ledger WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, int(limit)),
    ).fetchall()


def list_users_with_balances(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    return conn.execute(
        "SELECT u.id, u.email, u.is_admin, u.ai_provider, u.ai_model, u.ai_api_key, u.ai_base_url, "
        "u.workflow_max_directions, u.workflow_max_results_per_direction, u.created_at, "
        "COALESCE(a.credits_balance, 0) AS credits_balance, COALESCE(a.credits_unlimited, 0) AS credits_unlimited "
        "FROM users u LEFT JOIN accounts a ON a.user_id = u.id ORDER BY u.created_at DESC"
    ).fetchall()


def set_user_admin(conn: sqlite3.Connection, user_id: int, is_admin: bool) -> None:
    conn.execute(
        "UPDATE users SET is_admin = ? WHERE id = ?",
        (1 if is_admin else 0, user_id),
    )
    now = utc_now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO accounts(user_id, credits_balance, credits_unlimited, updated_at) VALUES (?, 0, ?, ?)",
        (user_id, 1 if is_admin else 0, now),
    )
    conn.execute(
        "UPDATE accounts SET credits_unlimited = ?, updated_at = ? WHERE user_id = ?",
        (1 if is_admin else 0, now, user_id),
    )


def adjust_credits(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    delta: int,
    reason: str = "admin_adjustment",
    actor_user_id: Optional[int] = None,
) -> int:
    """调整用户余额，返回最新余额。"""
    now = utc_now_iso()
    with transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO accounts(user_id, credits_balance, updated_at) VALUES (?, 0, ?)",
            (user_id, now),
        )
        row = conn.execute("SELECT credits_balance FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
        balance = int(row["credits_balance"] or 0) if row else 0
        new_balance = balance + int(delta)
        if new_balance < 0:
            raise RuntimeError("调整后余额不能为负数")
        conn.execute(
            "UPDATE accounts SET credits_balance = ?, updated_at = ? WHERE user_id = ?",
            (new_balance, now, user_id),
        )
        conn.execute(
            "INSERT INTO credit_ledger(id, user_id, entry_type, units, reason, idempotency_key, created_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                str(uuid.uuid4()),
                user_id,
                "credit" if delta >= 0 else "debit",
                abs(int(delta)),
                reason,
                now,
                json.dumps({"actor_user_id": actor_user_id}) if actor_user_id else None,
            ),
        )
        return new_balance


def _ensure_admin_column(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(users)").fetchall()
    column_names = {str(row["name"]) for row in info}
    if "is_admin" not in column_names:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;")


def _ensure_users_ai_columns(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(users)").fetchall()
    column_names = {str(row["name"]) for row in info}
    if "ai_provider" not in column_names:
        conn.execute("ALTER TABLE users ADD COLUMN ai_provider TEXT NOT NULL DEFAULT '';")
    if "ai_model" not in column_names:
        conn.execute("ALTER TABLE users ADD COLUMN ai_model TEXT NOT NULL DEFAULT '';")


def _ensure_users_ai_secret_columns(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(users)").fetchall()
    column_names = {str(row["name"]) for row in info}
    if "ai_api_key" not in column_names:
        conn.execute("ALTER TABLE users ADD COLUMN ai_api_key TEXT NOT NULL DEFAULT '';")
    if "ai_base_url" not in column_names:
        conn.execute("ALTER TABLE users ADD COLUMN ai_base_url TEXT NOT NULL DEFAULT '';")


def _ensure_users_workflow_limit_columns(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(users)").fetchall()
    column_names = {str(row["name"]) for row in info}
    if "workflow_max_directions" not in column_names:
        conn.execute("ALTER TABLE users ADD COLUMN workflow_max_directions INTEGER NOT NULL DEFAULT 6;")
    if "workflow_max_results_per_direction" not in column_names:
        conn.execute(
            "ALTER TABLE users ADD COLUMN workflow_max_results_per_direction INTEGER NOT NULL DEFAULT 3;"
        )


def _ensure_accounts_unlimited_column(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(accounts)").fetchall()
    column_names = {str(row["name"]) for row in info}
    if "credits_unlimited" not in column_names:
        conn.execute("ALTER TABLE accounts ADD COLUMN credits_unlimited INTEGER NOT NULL DEFAULT 0;")


def _backfill_admin_unlimited(conn: sqlite3.Connection) -> None:
    account_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "credits_unlimited" in account_columns:
        conn.execute(
            "UPDATE accounts SET credits_unlimited = 1 "
            "WHERE user_id IN (SELECT id FROM users WHERE is_admin = 1);"
        )


def _backfill_workflow_limit_defaults(conn: sqlite3.Connection) -> None:
    user_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "workflow_max_directions" not in user_columns or "workflow_max_results_per_direction" not in user_columns:
        return
    conn.execute(
        "UPDATE users SET workflow_max_directions = 6 "
        "WHERE is_admin = 0 AND workflow_max_directions = 12;"
    )
    conn.execute(
        "UPDATE users SET workflow_max_results_per_direction = 3 "
        "WHERE is_admin = 0 AND workflow_max_results_per_direction = 50;"
    )
