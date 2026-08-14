"""Database engine management.

Creates read-only SQLite connections by default. The read-only URI is a
*physical* guarantee: even if a malicious write query slips past the SQL
guard, the connection itself refuses to mutate the file.
"""

import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote

from config import Settings, get_settings

_lock = threading.Lock()


def _readonly_uri(db_path: str) -> str:
    """Build a `file:...?mode=ro` URI, percent-encoding the path."""
    quoted = quote(str(db_path), safe="/:\\")
    return f"file:{quoted}?mode=ro&uri=true"


def create_readonly_connection(db_path: Path | None = None, settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    path = db_path or settings.db_path
    conn = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    # Belt-and-braces: enforce read-only at the SQLite level too.
    conn.execute("PRAGMA query_only = ON")
    return conn


def get_db_connection(db_path: Path | None = None) -> sqlite3.Connection:
    return create_readonly_connection(db_path)


def database_exists(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.db_path.exists() and settings.db_path.stat().st_size > 0


def dispose_engine(db_path: Path | None = None, settings: Settings | None = None) -> None:
    """No-op kept for API symmetry with pooled engines; SQLite needs no pooling."""
    pass
