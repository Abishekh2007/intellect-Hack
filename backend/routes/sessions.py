"""Session management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from store import session_store

router = APIRouter(prefix="/api", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str = "New chat"


class SessionRename(BaseModel):
    title: str


@router.get("/sessions")
def list_sessions() -> list[dict]:
    return session_store.list_sessions()


@router.post("/sessions")
def create_session(body: SessionCreate) -> dict:
    session_id = session_store.create_session(body.title)
    return {"session_id": session_id, "title": body.title}


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = session_store.list_messages(session_id)
    return {"session": session, "messages": messages}


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: SessionRename) -> dict:
    if not session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    session_store.rename_session(session_id, body.title)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    session_store.delete_session(session_id)
    return {"ok": True}