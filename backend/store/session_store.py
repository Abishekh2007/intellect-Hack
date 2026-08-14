"""Persistent session storage (SQLite).

Stores sessions, messages, and dashboard-pinned items. File-backed so history
survives restarts (a real differentiator vs localStorage-only peers).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from config import get_settings

_lock = threading.Lock()
_db_path: Path | None = None


def _conn() -> sqlite3.Connection:
    global _db_path
    settings = get_settings()
    _db_path = _db_path or (settings.db_path.parent / "datapilot_chat.db")
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    _init(conn)
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
            payload TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS dashboard_items (
            id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, title TEXT,
            payload TEXT, created_at TEXT
        )"""
    )
    conn.commit()


def create_session(title: str = "New chat") -> str:
    session_id = uuid.uuid4().hex
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?,?,datetime('now'),datetime('now'))",
                (session_id, title),
            )
            conn.commit()
        finally:
            conn.close()
    return session_id


def list_sessions() -> list[dict[str, Any]]:
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        finally:
            conn.close()
    return dict(row) if row else None


def rename_session(session_id: str, title: str) -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "UPDATE sessions SET title=?, updated_at=datetime('now') WHERE id=?",
                (title, session_id),
            )
            conn.commit()
        finally:
            conn.close()


def delete_session(session_id: str) -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM dashboard_items WHERE session_id=?", (session_id,))
            conn.commit()
        finally:
            conn.close()


def add_message(session_id: str, role: str, content: str, payload: dict[str, Any] | None = None) -> None:
    msg_id = uuid.uuid4().hex
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content, payload, created_at) VALUES (?,?,?,?,?,datetime('now'))",
                (msg_id, session_id, role, content, json.dumps(payload or {}, default=str)),
            )
            conn.execute(
                "UPDATE sessions SET updated_at=datetime('now') WHERE id=?", (session_id,)
            )
            conn.commit()
        finally:
            conn.close()


def list_messages(session_id: str) -> list[dict[str, Any]]:
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at", (session_id,)
            ).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        except json.JSONDecodeError:
            d["payload"] = {}
        out.append(d)
    return out


def pin_dashboard_item(session_id: str, kind: str, title: str, payload: dict[str, Any]) -> str:
    item_id = uuid.uuid4().hex
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO dashboard_items (id, session_id, kind, title, payload, created_at) VALUES (?,?,?,?,?,datetime('now'))",
                (item_id, session_id, kind, title, json.dumps(payload, default=str)),
            )
            conn.commit()
        finally:
            conn.close()
    return item_id


def list_dashboard_items(session_id: str) -> list[dict[str, Any]]:
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT * FROM dashboard_items WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        except json.JSONDecodeError:
            d["payload"] = {}
        out.append(d)
    return out


def delete_dashboard_item(item_id: str) -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute("DELETE FROM dashboard_items WHERE id=?", (item_id,))
            conn.commit()
        finally:
            conn.close()