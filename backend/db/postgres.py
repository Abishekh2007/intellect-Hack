"""PostgreSQL access.

Mirrors the SQLite path's guarantees on a different engine:

- the session is opened ``default_transaction_read_only=on``, so the server
  itself refuses to mutate anything even if a write slipped past the guard —
  the equivalent of SQLite's ``mode=ro`` URI;
- ``statement_timeout`` is set server-side, which is stronger than the SQLite
  watchdog because the database enforces it rather than a timer thread;
- results are capped and marked truncated the same way.

Engines are cached per URL because SQLAlchemy engines own a connection pool
and are meant to be long-lived.
"""

from __future__ import annotations

import threading
from typing import Any

_engines: dict[str, Any] = {}
_engine_lock = threading.Lock()

STATEMENT_TIMEOUT_MS = 15_000
CONNECT_TIMEOUT_SECONDS = 5


class PostgresUnavailable(Exception):
    """The driver isn't installed or the server can't be reached."""


def _require_sqlalchemy():
    try:
        import sqlalchemy
    except ImportError as exc:  # pragma: no cover - depends on install
        raise PostgresUnavailable(
            "PostgreSQL support needs SQLAlchemy and psycopg. "
            "Install them with: pip install 'sqlalchemy>=2.0' 'psycopg[binary]'"
        ) from exc
    return sqlalchemy


def get_engine(url: str):
    """Return a cached, read-only engine for this URL."""
    with _engine_lock:
        engine = _engines.get(url)
        if engine is not None:
            return engine

    sqlalchemy = _require_sqlalchemy()
    engine = sqlalchemy.create_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        connect_args={
            # Without this a wrong host hangs on the OS TCP timeout — over two
            # minutes — which reads as the whole app freezing.
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            # Enforced by the server for every statement on this connection.
            "options": (
                f"-c default_transaction_read_only=on "
                f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
            ),
        },
    )
    with _engine_lock:
        _engines[url] = engine
    return engine


def check_connection(url: str) -> dict[str, Any]:
    """Verify a URL before it is saved, so bad input fails at setup time."""
    sqlalchemy = _require_sqlalchemy()
    engine = get_engine(url)
    with engine.connect() as conn:
        version = conn.execute(sqlalchemy.text("SELECT version()")).scalar()
        tables = conn.execute(
            sqlalchemy.text(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
            )
        ).scalar()
    return {"server": (version or "").split(",")[0], "table_count": int(tables or 0)}


def execute(url: str, sql: str, max_rows: int) -> dict[str, Any]:
    """Run already-validated read-only SQL. Returns the access-layer shape."""
    sqlalchemy = _require_sqlalchemy()
    engine = get_engine(url)
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(sql))
        columns = list(result.keys())
        raw = result.fetchmany(max_rows + 1)
    truncated = len(raw) > max_rows
    rows = [list(r) for r in raw[:max_rows]]
    return {"columns": columns, "rows": rows, "truncated": truncated}


_SCHEMA_SQL = """
SELECT c.table_name, c.column_name, c.data_type, c.is_nullable, c.ordinal_position
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_name = c.table_name AND t.table_schema = c.table_schema
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND t.table_type = 'BASE TABLE'
ORDER BY c.table_name, c.ordinal_position
"""

_KEYS_SQL = """
SELECT
    tc.constraint_type,
    kcu.table_name,
    kcu.column_name,
    ccu.table_name  AS references_table,
    ccu.column_name AS references_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
LEFT JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
 AND tc.table_schema = ccu.table_schema
WHERE tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
  AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
"""


def discover_schema(url: str) -> dict[str, Any]:
    """Same JSON shape as the SQLite discovery, so callers can't tell them
    apart — the ER diagram builder and prompt renderer are shared."""
    sqlalchemy = _require_sqlalchemy()
    engine = get_engine(url)
    with engine.connect() as conn:
        column_rows = conn.execute(sqlalchemy.text(_SCHEMA_SQL)).fetchall()
        key_rows = conn.execute(sqlalchemy.text(_KEYS_SQL)).fetchall()

    primary_keys: dict[str, set[str]] = {}
    foreign_keys: dict[str, list[dict[str, str]]] = {}
    for constraint_type, table, column, ref_table, ref_column in key_rows:
        if constraint_type == "PRIMARY KEY":
            primary_keys.setdefault(table, set()).add(column)
        elif ref_table:
            foreign_keys.setdefault(table, []).append(
                {
                    "column": column,
                    "references_table": ref_table,
                    "references_column": ref_column,
                }
            )

    tables: dict[str, dict[str, Any]] = {}
    for table, column, data_type, is_nullable, _pos in column_rows:
        entry = tables.setdefault(
            table,
            {
                "name": table,
                "columns": [],
                "primary_keys": sorted(primary_keys.get(table, set())),
                "foreign_keys": foreign_keys.get(table, []),
            },
        )
        entry["columns"].append(
            {
                "name": column,
                "type": data_type,
                "nullable": is_nullable == "YES",
                "pk": column in primary_keys.get(table, set()),
            }
        )

    return {"tables": [tables[name] for name in sorted(tables)]}


def dispose_all() -> None:
    """Drop cached engines. Used by tests."""
    with _engine_lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
