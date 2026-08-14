"""Database endpoints: schema info, query execution, file upload."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from config import get_settings
from db.access_layer import execute_read_only
from db.connections import (
    SQLITE_KIND,
    get_session_connection,
    register_connection,
    set_session_connection,
)
from db.engine import create_readonly_connection
from db.file_ingest import ALLOWED_EXTENSIONS, ingest_upload
from db.schema_discovery import discover_schema, discover_schema_for

router = APIRouter(prefix="/api", tags=["database"])


class QueryRequest(BaseModel):
    sql: str


@router.get("/schema")
def schema(session_id: str | None = None) -> dict:
    return discover_schema_for(get_session_connection(session_id or ""))


@router.post("/query")
def run_query(body: QueryRequest, session_id: str | None = None) -> dict:
    try:
        return execute_read_only(body.sql, connection=get_session_connection(session_id or ""))
    except Exception as exc:  # noqa: BLE001
        error_type = getattr(exc, "error_type", "sql_error")
        message = getattr(exc, "message", str(exc))
        raise HTTPException(status_code=400, detail={"type": error_type, "message": message}) from exc


@router.get("/table-preview/{table_name}")
def table_preview(table_name: str, session_id: str | None = None) -> dict:
    """Preview a table on whichever database the session is using.

    The table name is checked against the live schema rather than
    interpolated blind, so it cannot be used to smuggle SQL.
    """
    connection = get_session_connection(session_id or "")
    schema_info = discover_schema_for(connection)
    known = {t["name"] for t in schema_info["tables"]}
    if table_name not in known:
        raise HTTPException(status_code=404, detail="Table not found")

    quoted = table_name.replace('"', '""')
    try:
        return execute_read_only(
            f'SELECT * FROM "{quoted}" LIMIT 50', connection=connection, max_rows=50
        )
    except Exception as exc:  # noqa: BLE001
        message = getattr(exc, "message", str(exc))
        raise HTTPException(status_code=400, detail={"message": message}) from exc

@router.post("/upload")
async def upload_database(file: UploadFile = File(...), session_id: str | None = None) -> dict:
    """Register an uploaded SQLite file as a new connection.

    It is added alongside the demo database rather than replacing it, so the
    demo data is always one click away and one user's upload cannot redirect
    everyone else's queries.
    """
    settings = get_settings()
    content = await file.read()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".db", ".sqlite", ".sqlite3"):
        raise HTTPException(status_code=400, detail="Only .db/.sqlite/.sqlite3 files are supported.")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Database too large (max 50 MB).")

    upload_dir = settings.db_path.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / (Path(file.filename).name)
    dest.write_bytes(content)

    # Validate it opens and has at least one table.
    try:
        conn = sqlite3.connect(str(dest))
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if not tables:
                raise HTTPException(status_code=400, detail="Uploaded file contains no tables.")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail=f"Not a valid SQLite database: {exc}") from exc

    connection = register_connection(Path(file.filename).stem, SQLITE_KIND, str(dest))
    # Switch only the uploading session over to it.
    if session_id:
        set_session_connection(session_id, connection.id)
    return {
        "ok": True,
        "connection": connection.public(),
        "tables": [t[0] for t in tables],
    }


@router.post("/upload-file")
async def upload_data_file(file: UploadFile = File(...)) -> dict:
    """Ingest a CSV/XLSX/PDF/DOCX/JSON file into a queryable table."""
    settings = get_settings()
    content = await file.read()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    # Write to the active DB (needs a writable connection — open separately).
    conn = sqlite3.connect(str(settings.db_path))
    try:
        info = ingest_upload(file.filename or "upload", content, conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "info": info}