"""Server-side store for query result sets.

The agent loop hands the model a *summary* of every query result — columns,
types, row count and a short preview — and keeps the full rows here under a
``result_id``. Downstream tools (``generate_chart``, ``explain_data``) take
that id and read the rows back out server-side.

Two things fall out of this:

- a 500-row result costs the same context as a 5-row one, and the rows never
  make a round trip out to the model and back just to be charted;
- charts and statistics are computed over the *real* rows, so a model that
  paraphrases numbers cannot corrupt them.

The store is process-local and bounded — results are turn-scoped working
state, not durable data.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from typing import Any

# Enough to cover the tool calls of a few recent turns, small enough that a
# long session can't grow without bound.
MAX_RESULTS = 64

# How many rows the model is shown inline. Enough to reason about shape and
# spot obvious outliers; short enough to stay cheap.
PREVIEW_ROWS = 20

_lock = threading.Lock()
_results: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


def _classify(values: list[Any]) -> str:
    """Best-effort column type, for the model's benefit."""
    seen = [v for v in values if v is not None]
    if not seen:
        return "empty"
    numeric = 0
    for v in seen:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            numeric += 1
        elif isinstance(v, str):
            try:
                float(v.replace(",", ""))
                numeric += 1
            except ValueError:
                pass
    return "number" if numeric / len(seen) > 0.8 else "text"


def put(result: dict[str, Any], session_id: str = "") -> str:
    """Store a full result set and return its id."""
    result_id = f"res_{uuid.uuid4().hex[:12]}"
    with _lock:
        _results[result_id] = {"session_id": session_id, "result": result}
        _results.move_to_end(result_id)
        while len(_results) > MAX_RESULTS:
            _results.popitem(last=False)
    return result_id


def get(result_id: str) -> dict[str, Any] | None:
    """Return the full stored result, or None if unknown or evicted."""
    with _lock:
        entry = _results.get(result_id)
        if entry is None:
            return None
        _results.move_to_end(result_id)
        return entry["result"]


def rows_as_dicts(result_id: str) -> list[dict[str, Any]] | None:
    """Return the stored rows as row objects, the shape the viz layer wants."""
    result = get(result_id)
    if result is None:
        return None
    columns = result.get("columns", [])
    return [dict(zip(columns, row)) for row in result.get("rows", [])]


def summarize(result: dict[str, Any], result_id: str) -> dict[str, Any]:
    """The model-facing view of a result: shape, not bulk.

    Includes an explicit instruction to pass ``result_id`` onward, because a
    model that can see rows will otherwise copy them into the next call.
    """
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    column_types = {
        col: _classify([row[i] for row in rows if i < len(row)])
        for i, col in enumerate(columns)
    }
    preview = [dict(zip(columns, row)) for row in rows[:PREVIEW_ROWS]]
    summary = {
        "result_id": result_id,
        "sql": result.get("sql", ""),
        "columns": columns,
        "column_types": column_types,
        "row_count": result.get("row_count", len(rows)),
        "truncated": result.get("truncated", False),
        "execution_time_ms": result.get("execution_time_ms"),
        "preview_rows": preview,
    }
    if len(rows) > len(preview):
        summary["preview_note"] = (
            f"Showing the first {len(preview)} of {len(rows)} rows."
        )
    summary["usage"] = (
        "The full result is held server-side. Pass result_id to generate_chart "
        "or explain_data — do not copy rows into those calls."
    )
    return summary


def clear() -> None:
    """Drop everything. Used by tests."""
    with _lock:
        _results.clear()
