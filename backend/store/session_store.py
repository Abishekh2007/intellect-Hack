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
_initialized = False


def _conn() -> sqlite3.Connection:
    """Open a connection, creating the schema once per process.

    `_init` used to run on every single call: six CREATE TABLE IF NOT EXISTS
    statements, a PRAGMA, a migration check and a commit before every message
    read and write. The schema cannot change while the process is alive, so
    the work was pure overhead on the hottest path in the app.
    """
    global _db_path, _initialized
    settings = get_settings()
    _db_path = _db_path or (settings.db_path.parent / "datapilot_chat.db")
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    if not _initialized:
        _init(conn)
        _initialized = True
    return conn


def reset_for_tests() -> None:
    """Forget the cached path and schema flag (tests point at a temp file)."""
    global _db_path, _initialized
    _db_path = None
    _initialized = False


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
            payload TEXT, created_at TEXT, seq INTEGER DEFAULT 0
        )"""
    )
    # created_at has one-second resolution, which is too coarse to order a
    # question and its answer. seq is the real ordering key; migrate old files.
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    if "seq" not in existing:
        conn.execute("ALTER TABLE messages ADD COLUMN seq INTEGER DEFAULT 0")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS dashboard_items (
            id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, title TEXT,
            payload TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY, kind TEXT, title TEXT, payload TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS connections (
            id TEXT PRIMARY KEY, name TEXT, kind TEXT, target TEXT, created_at TEXT
        )"""
    )
    # Which database each session is pointed at. Server-side by design: the
    # model must not be able to choose the database it queries.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS session_connections (
            session_id TEXT PRIMARY KEY, connection_id TEXT
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
            next_seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM messages WHERE session_id=?",
                (session_id,),
            ).fetchone()["n"]
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content, payload, created_at, seq)"
                " VALUES (?,?,?,?,?,datetime('now'),?)",
                (msg_id, session_id, role, content, json.dumps(payload or {}, default=str), next_seq),
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
                "SELECT * FROM messages WHERE session_id=? ORDER BY seq, created_at",
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


def add_connection(name: str, kind: str, target: str) -> str:
    connection_id = uuid.uuid4().hex[:12]
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO connections (id, name, kind, target, created_at)"
                " VALUES (?,?,?,?,datetime('now'))",
                (connection_id, name, kind, target),
            )
            conn.commit()
        finally:
            conn.close()
    return connection_id


def list_connections() -> list[dict[str, Any]]:
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute("SELECT * FROM connections ORDER BY created_at").fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def get_connection(connection_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT * FROM connections WHERE id=?", (connection_id,)).fetchone()
        finally:
            conn.close()
    return dict(row) if row else None


def delete_connection(connection_id: str) -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute("DELETE FROM connections WHERE id=?", (connection_id,))
            # Any session left pointing at it falls back to the demo database.
            conn.execute(
                "DELETE FROM session_connections WHERE connection_id=?", (connection_id,)
            )
            conn.commit()
        finally:
            conn.close()


def set_session_connection(session_id: str, connection_id: str) -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO session_connections (session_id, connection_id) VALUES (?,?)"
                " ON CONFLICT(session_id) DO UPDATE SET connection_id=excluded.connection_id",
                (session_id, connection_id),
            )
            conn.commit()
        finally:
            conn.close()


def get_session_connection(session_id: str) -> str | None:
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT connection_id FROM session_connections WHERE session_id=?", (session_id,)
            ).fetchone()
        finally:
            conn.close()
    return row["connection_id"] if row else None


def create_share(kind: str, title: str, payload: dict[str, Any]) -> str:
    """Persist a shared view. Links must outlive a server restart."""
    share_id = uuid.uuid4().hex[:8]
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO shares (id, kind, title, payload, created_at)"
                " VALUES (?,?,?,?,datetime('now'))",
                (share_id, kind, title, json.dumps(payload, default=str)),
            )
            conn.commit()
        finally:
            conn.close()
    return share_id


def get_share(share_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
    except json.JSONDecodeError:
        d["payload"] = {}
    return d