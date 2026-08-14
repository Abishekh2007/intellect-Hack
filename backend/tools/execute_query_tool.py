"""execute_query tool — run a validated read-only SQL query."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from db.access_layer import execute_read_only
from memory.session_context import get_current_session_id
from store import result_store
from tools.registry import ToolDefinition, ToolError


class ExecuteQueryInput(BaseModel):
    query: str = Field(description="A single read-only SELECT SQL statement.")


def _execute_query_handler(args: ExecuteQueryInput, context: dict[str, Any]) -> dict[str, Any]:
    settings = context.get("settings")
    try:
        result = execute_read_only(
            args.query,
            db_path=context.get("db_path"),
            max_rows=settings.hard_row_ceiling,
            connection=context.get("connection"),
        )
    except Exception as exc:  # noqa: BLE001
        error_type = getattr(exc, "error_type", "sql_error")
        message = getattr(exc, "message", str(exc))
        raise ToolError(error_type, message, recoverable=True) from exc

    # Park the full result server-side and hand the model its shape. A wide
    # result then costs the same context as a narrow one.
    result_id = result_store.put(result, session_id=get_current_session_id())
    return result_store.summarize(result, result_id)


execute_query_tool = ToolDefinition(
    name="execute_query",
    description=(
        "Execute a read-only SQL SELECT query against the database. Returns the "
        "result's shape — columns, types, row count and a preview of the first "
        "rows — plus a result_id referring to the full result held server-side. "
        "Pass that result_id to generate_chart or explain_data rather than "
        "copying rows between calls. Only SELECT queries are permitted; write "
        "operations are blocked for safety."
    ),
    input_model=ExecuteQueryInput,
    handler=_execute_query_handler,
)