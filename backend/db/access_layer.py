"""Safe query execution.

Runs only SQL that already passed :func:`security.sql_guard.validate_sql` on a
read-only connection, applies a hard row ceiling, truncation detection and a
watchdog timeout (SQLite has no native statement timeout, so we interrupt from
a timer thread).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from config import get_settings
from db.engine import create_readonly_connection
from security import sql_guard
from security.sql_guard import sanitize_db_error


class QueryTimeoutError(Exception):
    pass


class QueryExecutionError(Exception):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def _run_with_timeout(db_path: Path, sql: str, timeout_seconds: int = 15) -> list[Any]:
    """Run a query on a worker thread; interrupt the connection on timeout.

    The SQLite connection is created inside the worker thread (SQLite
    connections are thread-bound); the main thread may call ``interrupt()``
    from outside, which is explicitly allowed and stops a running query.
    """
    holder: dict[str, Any] = {"rows": None, "error": None, "conn": None}

    def worker() -> None:
        conn = None
        try:
            conn = create_readonly_connection(db_path)
            holder["conn"] = conn
            holder["rows"] = conn.execute(sql).fetchall()
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc
        finally:
            if conn is not None:
                conn.close()
            holder["conn"] = None

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        conn = holder.get("conn")
        try:
            if conn is not None:
                conn.interrupt()
        except Exception:  # noqa: BLE001
            pass
        thread.join(1)
        raise QueryTimeoutError("Query timed out after %d seconds." % timeout_seconds)
    if holder["error"] is not None:
        raise holder["error"]
    return holder["rows"]


def execute_read_only(
    sql: str,
    *,
    db_path: Optional[Path] = None,
    max_rows: Optional[int] = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Validate and execute a read-only query.

    Returns:
        {
          "sql": str,
          "columns": [str],
          "rows": [[..]],
          "row_count": int,
          "truncated": bool,
          "execution_time_ms": float,
        }
    """
    settings = get_settings()
    max_rows = max_rows or settings.hard_row_ceiling

    # Validate (always enforce a cap even if the model already put one).
    validation = sql_guard.validate_sql(sql, enforce_limit=True, max_rows=settings.hard_row_ceiling)
    if not validation.valid:
        raise QueryExecutionError(validation.error_type, validation.error_message)

    safe_sql = validation.sql
    start = time.perf_counter()
    try:
        raw_rows = _run_with_timeout(db_path, safe_sql, timeout_seconds=timeout_seconds)
    except QueryTimeoutError as exc:
        raise QueryExecutionError("timeout", str(exc)) from exc
    except sqlite3.Error as exc:
        raise QueryExecutionError("sql_error", sanitize_db_error(exc)) from exc
    elapsed = (time.perf_counter() - start) * 1000.0

    columns: list[str] = []
    if raw_rows:
        first = raw_rows[0]
        if hasattr(first, "keys"):
            columns = list(first.keys())
        else:
            columns = list(first) if isinstance(first, (tuple, list)) else []
    rows: list[list[Any]] = []
    truncated = False
    for i, row in enumerate(raw_rows):
        if i >= max_rows:
            truncated = True
            break
        if hasattr(row, "keys"):
            values = [row[k] for k in row.keys()]
        else:
            values = list(row)
        rows.append([_json_safe(v) for v in values])
    return {
        "sql": safe_sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "execution_time_ms": round(elapsed, 2),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, bytes):
        return "<binary>"
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    try:
        import json

        return json.loads(json.dumps(value, default=str))
    except Exception:  # noqa: BLE001
        return str(value)