"""Chat endpoint — SSE streaming of agent turns."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.loop import DataPilotAgent
from config import get_settings
from store import session_store

router = APIRouter(prefix="/api", tags=["chat"])

_agent: DataPilotAgent | None = None


def get_agent() -> DataPilotAgent:
    global _agent
    if _agent is None:
        _agent = DataPilotAgent(get_settings())
    return _agent


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _event_stream(req: ChatRequest):
    agent = get_agent()
    session_id = req.session_id or session_store.create_session()

    # Persist the question before answering it, so a reloaded thread reads in
    # the order it happened.
    session_store.add_message(session_id, "user", req.message, {})

    events = []
    try:
        async for event in agent.stream_turn(req.message, session_id):
            events.append(event)
            if event.get("type") == "final":
                session_store.add_message(
                    session_id,
                    "assistant",
                    event.get("answer", ""),
                    {
                        "sql": event.get("sql"),
                        "table": event.get("table"),
                        "chart": event.get("chart"),
                        "diagram": event.get("diagram"),
                        "mode": event.get("mode"),
                    },
                )
            yield _sse(event["type"], event)
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": f"Unexpected error: {exc}"})

    if not events:
        yield _sse("error", {"message": "No events produced."})


@router.post("/chat")
async def chat(req: ChatRequest):
    headers = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
    return StreamingResponse(_event_stream(req), media_type="text/event-stream", headers=headers)