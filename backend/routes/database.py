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
from db.file_ingest import ALLOWED_EXTENSIONS, ingest_upload
from db.schema_discovery import discover_schema_for

router = APIRouter(prefix="/api", tags=["database"])

# Read uploads in chunks so an oversized file is rejected at the threshold
# rather than after the whole thing is already resident. `await file.read()`
# pulled the entire body into memory first and only then checked the size, so
# the limit protected the disk but not the process.
_UPLOAD_CHUNK = 1024 * 1024


async def _read_capped(file: UploadFile, limit: int, message: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=message)
        chunks.append(chunk)
    if not total:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    return b"".join(chunks)


def _unique_destination(directory: Path, filename: str) -> Path:
    """A path that cannot collide with an existing upload.

    ``filename`` is reduced to its basename by the caller, so a crafted name
    like ``../../ecommerce.db`` cannot escape the uploads directory.
    """
    stem = Path(filename).stem or "database"
    suffix = Path(filename).suffix or ".db"
    dest = directory / f"{stem}{suffix}"
    n = 2
    while dest.exists():
        dest = directory / f"{stem}_{n}{suffix}"
        n += 1
    return dest


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
    filename = Path(file.filename or "").name
    ext = Path(filename).suffix.lower()
    if ext not in (".db", ".sqlite", ".sqlite3"):
        raise HTTPException(status_code=400, detail="Only .db/.sqlite/.sqlite3 files are supported.")
    content = await _read_capped(file, 50 * 1024 * 1024, "Database too large (max 50 MB).")

    upload_dir = settings.db_path.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    # A per-upload subdirectory. Writing straight into `uploads/` meant a
    # second upload of "data.db" silently overwrote the first — and every
    # session still pointing at it started reading someone else's rows.
    dest = _unique_destination(upload_dir, filename)
    dest.write_bytes(content)

    # Validate it opens and has at least one table.
    try:
        conn = sqlite3.connect(str(dest))
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="That file is not a valid SQLite database.") from exc
    if not tables:
        # Don't leave a rejected upload on disk.
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file contains no tables.")

    connection = register_connection(Path(filename).stem or "Uploaded database", SQLITE_KIND, str(dest))
    # Switch only the uploading session over to it.
    if session_id:
        set_session_connection(session_id, connection.id)
    return {
        "ok": True,
        "connection": connection.public(),
        "tables": [t[0] for t in tables],
    }


@router.post("/upload-file")
async def upload_data_file(
    file: UploadFile = File(...), session_id: str | None = None
) -> dict:
    """Ingest a CSV/XLSX/PDF/DOCX/JSON file into a queryable SQLite table.

    The table lands in a workbook database belonging to this session, which is
    then selected for it. It used to be written straight into the seeded demo
    file: the write went to a database every other session also reads, so one
    user's spreadsheet appeared in everybody's schema panel, the demo dataset
    was permanently altered, and re-seeding wiped the import without warning.
    """
    settings = get_settings()
    filename = Path(file.filename or "upload").name
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    content = await _read_capped(file, 25 * 1024 * 1024, "File too large (max 25 MB).")

    connection = get_session_connection(session_id or "")
    if connection.is_demo or connection.kind != SQLITE_KIND:
        # Never write to the demo file, and never to Postgres. Give this
        # session its own workbook and point it there.
        upload_dir = settings.db_path.parent / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique_destination(upload_dir, "workbook.db")
        connection = register_connection(f"Imported data ({filename})", SQLITE_KIND, str(dest))
        if session_id:
            set_session_connection(session_id, connection.id)
    else:
        dest = connection.db_path

    conn = sqlite3.connect(str(dest))
    try:
        info = ingest_upload(filename, content, conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "info": info, "connection": connection.public()}