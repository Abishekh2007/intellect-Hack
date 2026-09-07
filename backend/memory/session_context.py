"""Session identity via ContextVar.

The session_id lives in a ContextVar, never in any LLM-facing tool schema, so
concurrent requests can never address another user's database. Tools resolve
their owning session from context instead of trusting the model.
"""

from __future__ import annotations

import contextvars
from typing import Any

_current_session: contextvars.ContextVar[str] = contextvars.ContextVar("current_session", default="")
# The default is None, not []. A mutable default is created once and shared by
# every context that never calls set(), so trace() appended into one global
# list that grew forever and mixed events from unrelated sessions together.
_current_trace: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "current_trace", default=None
)


class SessionScope:
    """Context manager that sets the session id for the duration of a turn."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._token = None

    def __enter__(self) -> "SessionScope":
        self._token = _current_session.set(self.session_id)
        _current_trace.set([])
        return self

    def __exit__(self, *exc) -> None:
        _current_session.reset(self._token)
        _current_trace.set([])


def get_current_session_id() -> str:
    return _current_session.get()


def get_current_trace() -> list[dict[str, Any]]:
    return list(_current_trace.get() or [])


def trace(event: str, payload: dict[str, Any] | None = None) -> None:
    entries = _current_trace.get()
    if entries is None:
        entries = []
        _current_trace.set(entries)
    entries.append({"event": event, **(payload or {})})