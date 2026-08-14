"""FastAPI application entrypoint.

Binds all routers, wires CORS, and seeds the demo database on startup.
Run:  uvicorn main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from db.seed import ensure_seeded
from routes import (
    chat_router,
    dashboard_router,
    database_router,
    health_router,
    sessions_router,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_seeded(settings.db_path)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(database_router)
app.include_router(dashboard_router)


@app.get("/")
def root() -> dict:
    return {"app": settings.app_name, "docs": "/docs", "health": "/health"}