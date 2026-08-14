"""REST + SSE route handlers for the DataPilot API."""

from .chat import router as chat_router
from .dashboard import router as dashboard_router
from .database import router as database_router
from .health import router as health_router
from .sessions import router as sessions_router
from .queries import router as queries_router

__all__ = ["chat_router", "dashboard_router", "database_router", "health_router", "sessions_router", "queries_router"]