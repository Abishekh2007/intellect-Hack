"""Build the fully-populated tool registry with shared context wiring."""

from __future__ import annotations

from tools.execute_query_tool import execute_query_tool
from tools.explain_data_tool import explain_data_tool
from tools.generate_chart_tool import generate_chart_tool
from tools.generate_flowchart_tool import generate_flowchart_tool
from tools.get_schema_tool import get_schema_tool
from tools.registry import ToolRegistry
from tools.verify_response_tool import verify_response_tool


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(get_schema_tool)
    registry.register(execute_query_tool)
    registry.register(generate_chart_tool)
    registry.register(generate_flowchart_tool)
    registry.register(explain_data_tool)
    registry.register(verify_response_tool)
    return registry


def default_context(settings) -> dict:
    """Shared context every tool receives.

    ``connection`` decides which database the tools read. It is resolved
    server-side from the session and deliberately absent from every tool
    schema, so the model cannot point a query at another database.
    """
    from db.connections import demo_connection

    return {"settings": settings, "connection": demo_connection()}
