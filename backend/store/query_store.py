import sqlite3
import uuid
import datetime
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "chat_history.db")

def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                id TEXT PRIMARY KEY,
                sql TEXT NOT NULL,
                is_favorite BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

_init_db()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def log_query(sql: str) -> str:
    query_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("INSERT INTO queries (id, sql, is_favorite, created_at) VALUES (?, ?, 0, ?)",
                     (query_id, sql, datetime.datetime.now(datetime.timezone.utc).isoformat()))
        conn.commit()
    return query_id

def get_queries(limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM queries ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

def toggle_favorite(query_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT is_favorite FROM queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            return {"error": "Query not found"}
        
        new_status = not row["is_favorite"]
        conn.execute("UPDATE queries SET is_favorite = ? WHERE id = ?", (new_status, query_id))
        conn.commit()
        return {"id": query_id, "is_favorite": new_status}
