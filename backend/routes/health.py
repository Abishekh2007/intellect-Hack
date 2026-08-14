"""Health and startup helpers."""

from __future__ import annotations

from fastapi import APIRouter

from config import get_settings
from db.engine import database_exists
from llm.failover import has_any_provider

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "database": "ready" if database_exists(settings) else "missing",
        "llm_provider": "configured" if has_any_provider(settings) else "offline_mode",
        "app": settings.app_name,
    }