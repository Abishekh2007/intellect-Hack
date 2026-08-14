"""Database connection registry.

The app can talk to more than one database at a time. A *connection* is a
named, persisted pointer to a database — the seeded demo SQLite file, an
uploaded SQLite file, or a PostgreSQL server — and each chat session points at
exactly one of them.

Two rules shape this module:

- The demo connection is built in and cannot be edited or removed, so a session
  can always be reset to a known-good database mid-demo.
- Which database a session uses is *server-side state keyed by session id*. It
  is never a tool argument, so the model cannot redirect a query at a database
  the user did not choose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import get_settings

DEMO_CONNECTION_ID = "demo"

SQLITE_KIND = "sqlite"
POSTGRES_KIND = "postgres"
SUPPORTED_KINDS = {SQLITE_KIND, POSTGRES_KIND}

# sqlglot dialect per kind, so the SQL guard parses what will actually run.
DIALECTS = {SQLITE_KIND: "sqlite", POSTGRES_KIND: "postgres"}

_POSTGRES_URL = re.compile(r"^postgres(ql)?(\+\w+)?://", re.IGNORECASE)


class ConnectionError_(Exception):
    """Raised when a connection cannot be resolved or is misconfigured."""


@dataclass
class Connection:
    id: str
    name: str
    kind: str
    # SQLite: filesystem path. Postgres: SQLAlchemy URL.
    target: str
    is_demo: bool = False

    @property
    def dialect(self) -> str:
        return DIALECTS.get(self.kind, "sqlite")

    @property
    def db_path(self) -> Path | None:
        return Path(self.target) if self.kind == SQLITE_KIND else None

    def public(self) -> dict[str, Any]:
        """Registry view for the UI — never leaks credentials."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "is_demo": self.is_demo,
            "location": redact_target(self.kind, self.target),
        }


def redact_target(kind: str, target: str) -> str:
    """Describe where a connection points without exposing a password."""
    if kind == SQLITE_KIND:
        return Path(target).name
    # postgresql+psycopg://user:secret@host/db -> postgresql://user@host/db
    shown = re.sub(r"^(\w+)\+\w+://", r"\1://", target)
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1@", shown)


def normalize_postgres_url(url: str) -> str:
    """Pin the driver so SQLAlchemy doesn't reach for psycopg2."""
    if not _POSTGRES_URL.match(url or ""):
        raise ConnectionError_(
            "A PostgreSQL URL must look like postgresql://user:password@host:5432/database"
        )
    if "+" in url.split("://", 1)[0]:
        return url
    return url.replace("postgres://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


def demo_connection() -> Connection:
    settings = get_settings()
    return Connection(
        id=DEMO_CONNECTION_ID,
        name="Demo e-commerce (SQLite)",
        kind=SQLITE_KIND,
        target=str(settings.db_path),
        is_demo=True,
    )


def _from_row(row: dict[str, Any]) -> Connection:
    return Connection(id=row["id"], name=row["name"], kind=row["kind"], target=row["target"])


def list_connections() -> list[Connection]:
    """Every connection, demo first."""
    from store import session_store

    return [demo_connection()] + [_from_row(r) for r in session_store.list_connections()]


def get_connection(connection_id: str) -> Connection:
    from store import session_store

    if not connection_id or connection_id == DEMO_CONNECTION_ID:
        return demo_connection()
    row = session_store.get_connection(connection_id)
    if row is None:
        raise ConnectionError_(f"Unknown connection: {connection_id}")
    return _from_row(row)


def register_connection(name: str, kind: str, target: str) -> Connection:
    from store import session_store

    if kind not in SUPPORTED_KINDS:
        raise ConnectionError_(f"Unsupported database type: {kind}")
    if kind == POSTGRES_KIND:
        target = normalize_postgres_url(target)
    connection_id = session_store.add_connection(name, kind, target)
    return Connection(id=connection_id, name=name, kind=kind, target=target)


def remove_connection(connection_id: str) -> None:
    from store import session_store

    if connection_id == DEMO_CONNECTION_ID:
        raise ConnectionError_("The demo database cannot be removed.")
    session_store.delete_connection(connection_id)


def get_session_connection(session_id: str) -> Connection:
    """The database this session queries. Defaults to the demo database.

    Falls back to the demo rather than raising if the stored connection has
    since been deleted — a session should never be stranded.
    """
    from store import session_store

    if not session_id:
        return demo_connection()
    connection_id = session_store.get_session_connection(session_id)
    if not connection_id:
        return demo_connection()
    try:
        return get_connection(connection_id)
    except ConnectionError_:
        return demo_connection()


def set_session_connection(session_id: str, connection_id: str) -> Connection:
    from store import session_store

    connection = get_connection(connection_id)  # validates before persisting
    session_store.set_session_connection(session_id, connection.id)
    return connection


def reset_session_connection(session_id: str) -> Connection:
    """Point a session back at the seeded demo database."""
    from store import session_store

    session_store.set_session_connection(session_id, DEMO_CONNECTION_ID)
    return demo_connection()
