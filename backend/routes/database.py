"""Database endpoints: schema info, query execution, file upload."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from config import get_settings
from db.access_layer import execute_read_only
from db.engine import create_readonly_connection
from db.file_ingest import ALLOWED_EXTENSIONS, ingest_upload
from db.schema_discovery import discover_schema

router = APIRouter(prefix="/api", tags=["database"])


class QueryRequest(BaseModel):
    sql: str


@router.get("/schema")
def schema() -> dict:
    settings = get_settings()
    conn = create_readonly_connection(settings.db_path)
    try:
        return discover_schema(conn)
    finally:
        conn.close()


@router.post("/query")
def run_query(body: QueryRequest) -> dict:
    try:
        return execute_read_only(body.sql)
    except Exception as exc:  # noqa: BLE001
        error_type = getattr(exc, "error_type", "sql_error")
        message = getattr(exc, "message", str(exc))
        raise HTTPException(status_code=400, detail={"type": error_type, "message": message}) from exc


@router.post("/upload")
async def upload_database(file: UploadFile = File(...)) -> dict:
    """Replace the active demo database with an uploaded SQLite file."""
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

    # Point the app at the uploaded DB for future queries.
    settings.db_path = dest
    return {"ok": True, "database": str(dest), "tables": [t[0] for t in tables]}


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