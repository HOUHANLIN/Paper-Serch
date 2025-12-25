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
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  user_id INTEGER PRIMARY KEY,
  credits_balance INTEGER NOT NULL DEFAULT 0,
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
    created_at: str


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[User]:
    row = conn.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return User(id=int(row["id"]), email=str(row["email"]), created_at=str(row["created_at"]))


def get_user_by_email(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()


def create_user(conn: sqlite3.Connection, *, email: str, password_hash: str, initial_credits: int) -> User:
    email_clean = email.strip().lower()
    now = utc_now_iso()
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
            (email_clean, password_hash, now),
        )
        user_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO accounts(user_id, credits_balance, updated_at) VALUES (?, ?, ?)",
            (user_id, int(initial_credits), now),
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

        row = conn.execute(
            "SELECT credits_balance FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        balance = int(row["credits_balance"] or 0) if row else 0
        if balance < 1:
            raise RuntimeError("余额不足：请先充值或联系管理员增加次数")

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
                "debit",
                1,
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
