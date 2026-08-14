"""Connection endpoints — register databases and point sessions at them.

Which database a session queries is server-side state keyed by session id. It
is never a tool argument and never trusted from the model, only from an
explicit user action here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import connections as conn_registry
from db.connections import (
    POSTGRES_KIND,
    ConnectionError_,
    get_session_connection,
    list_connections,
    register_connection,
    remove_connection,
    reset_session_connection,
    set_session_connection,
)
from db.schema_discovery import discover_schema_for

router = APIRouter(prefix="/api", tags=["connections"])


class PostgresConnectionCreate(BaseModel):
    name: str = Field(default="PostgreSQL", description="Display name for the connection.")
    url: str = Field(description="postgresql://user:password@host:5432/database")


class SelectConnection(BaseModel):
    connection_id: str


@router.get("/connections")
def get_connections(session_id: str | None = None) -> dict:
    active = get_session_connection(session_id or "")
    return {
        "connections": [c.public() for c in list_connections()],
        "active_id": active.id,
    }


@router.post("/connections/postgres")
def add_postgres(body: PostgresConnectionCreate) -> dict:
    """Register a PostgreSQL database after proving it is reachable."""
    from db import postgres

    try:
        url = conn_registry.normalize_postgres_url(body.url)
    except ConnectionError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Verify before persisting, so a typo fails here rather than mid-demo.
    try:
        info = postgres.check_connection(url)
    except postgres.PostgresUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Could not connect to that database: {exc}"
        ) from exc

    connection = register_connection(body.name, POSTGRES_KIND, url)
    return {"connection": connection.public(), **info}


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: str) -> dict:
    try:
        remove_connection(connection_id)
    except ConnectionError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/sessions/{session_id}/connection")
def select_connection(session_id: str, body: SelectConnection) -> dict:
    try:
        connection = set_session_connection(session_id, body.connection_id)
    except ConnectionError_ as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"connection": connection.public()}


@router.post("/sessions/{session_id}/connection/reset")
def reset_connection(session_id: str) -> dict:
    """Return this session to the seeded demo database."""
    return {"connection": reset_session_connection(session_id).public()}


@router.get("/sessions/{session_id}/schema")
def session_schema(session_id: str) -> dict:
    """Schema of whichever database this session is currently pointed at."""
    connection = get_session_connection(session_id)
    try:
        schema = discover_schema_for(connection)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read the schema: {exc}") from exc
    return {"connection": connection.public(), **schema}
