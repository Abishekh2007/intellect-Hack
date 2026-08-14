"""get_schema tool — retrieve the database schema (tables, columns, types)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from db.connections import demo_connection
from db.schema_discovery import discover_schema_for
from tools.registry import ToolDefinition


class GetSchemaInput(BaseModel):
    scope: str = Field(
        default="full",
        description="'full' returns every table; a table name returns only that table.",
    )


def _get_schema_handler(args: GetSchemaInput, context: dict[str, Any]) -> dict[str, Any]:
    connection = context.get("connection") or demo_connection()
    schema = discover_schema_for(connection)

    tables = schema["tables"]
    if args.scope and args.scope != "full":
        tables = [t for t in tables if t["name"] == args.scope]

    return {
        "tables": tables,
        "table_names": [t["name"] for t in tables],
    }


get_schema_tool = ToolDefinition(
    name="get_schema",
    description=(
        "Retrieve the database schema including tables, columns, data types, "
        "primary keys and foreign keys. Call this FIRST to understand what data "
        "is available before writing queries."
    ),
    input_model=GetSchemaInput,
    handler=_get_schema_handler,
)