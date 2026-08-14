"""Dashboard endpoints — pin/export/share visualizations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from store import session_store

router = APIRouter(prefix="/api", tags=["dashboard"])


class PinItem(BaseModel):
    session_id: str
    kind: str  # chart | diagram | insight
    title: str
    payload: dict


class ShareCreate(BaseModel):
    session_id: str
    item_id: str | None = None


@router.post("/dashboard/pin")
def pin_item(body: PinItem) -> dict:
    item_id = session_store.pin_dashboard_item(
        body.session_id, body.kind, body.title, body.payload
    )
    return {"item_id": item_id}


@router.get("/dashboard/{session_id}")
def get_dashboard(session_id: str) -> dict:
    return {"items": session_store.list_dashboard_items(session_id)}


@router.delete("/dashboard/item/{item_id}")
def delete_item(item_id: str) -> dict:
    session_store.delete_dashboard_item(item_id)
    return {"ok": True}


_shares: dict[str, dict] = {}


@router.post("/share")
def create_share(body: ShareCreate) -> dict:
    share_id = uuid.uuid4().hex[:8]
    if body.item_id:
        items = session_store.list_dashboard_items(body.session_id)
        item = next((i for i in items if i["id"] == body.item_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        _shares[share_id] = {"kind": item["kind"], "title": item["title"], "payload": item["payload"]}
    else:
        _shares[share_id] = {"kind": "dashboard", "title": "Shared dashboard", "payload": {"items": session_store.list_dashboard_items(body.session_id)}}
    return {"share_id": share_id, "url": f"/shared/{share_id}"}


@router.get("/shared/{share_id}")
def get_share(share_id: str) -> dict:
    if share_id not in _shares:
        raise HTTPException(status_code=404, detail="Share not found")
    return _shares[share_id]