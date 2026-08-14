"""Dashboard endpoints — pin/export/share visualizations."""

from __future__ import annotations

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


@router.post("/share")
def create_share(body: ShareCreate) -> dict:
    if body.item_id:
        items = session_store.list_dashboard_items(body.session_id)
        item = next((i for i in items if i["id"] == body.item_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        share_id = session_store.create_share(item["kind"], item["title"], item["payload"])
    else:
        share_id = session_store.create_share(
            "dashboard",
            "Shared dashboard",
            {"items": session_store.list_dashboard_items(body.session_id)},
        )
    return {"share_id": share_id, "url": f"/shared/{share_id}"}


@router.get("/shared/{share_id}")
def get_share(share_id: str) -> dict:
    share = session_store.get_share(share_id)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"kind": share["kind"], "title": share["title"], "payload": share["payload"]}