"""execute_query tool — run a validated read-only SQL query."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from db.access_layer import execute_read_only
from tools.registry import ToolDefinition, ToolError


class ExecuteQueryInput(BaseModel):
    query: str = Field(description="A single read-only SELECT SQL statement.")


def _execute_query_handler(args: ExecuteQueryInput, context: dict[str, Any]) -> dict[str, Any]:
    settings = context.get("settings")
    db_path = context.get("db_path")
    try:
        result = execute_read_only(
            args.query,
            db_path=db_path,
            max_rows=settings.hard_row_ceiling,
        )
    except Exception as exc:  # noqa: BLE001
        error_type = getattr(exc, "error_type", "sql_error")
        message = getattr(exc, "message", str(exc))
        raise ToolError(error_type, message, recoverable=True) from exc
    return result


execute_query_tool = ToolDefinition(
    name="execute_query",
    description=(
        "Execute a read-only SQL SELECT query against the database and return "
        "columns and rows. Only SELECT queries are permitted; write operations "
        "are blocked for safety."
    ),
    input_model=ExecuteQueryInput,
    handler=_execute_query_handler,
)