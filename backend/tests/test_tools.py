"""Tests for the tool registry and individual tools."""

from __future__ import annotations

import pytest

from tools.builder import build_registry


@pytest.fixture()
def registry(settings):
    reg = build_registry()
    return reg


@pytest.fixture()
def ctx(settings):
    return {"settings": settings}


def test_all_required_tools_present(registry):
    required = {
        "get_schema",
        "execute_query",
        "generate_chart",
        "generate_flowchart",
        "explain_data",
    }
    assert required.issubset(set(registry.names()))


def test_tool_schemas_are_json_schema(registry):
    for tool in registry.all():
        schema = tool.json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


def test_get_schema_returns_tables(registry, ctx):
    result = registry.dispatch("get_schema", {"scope": "full"}, ctx)
    assert result["success"] is True
    tables = result["data"]["tables"]
    assert any(t["name"] == "orders" for t in tables)


def test_execute_query_safe(registry, ctx):
    result = registry.dispatch("execute_query", {"query": "SELECT COUNT(*) AS c FROM orders"}, ctx)
    assert result["success"] is True
    assert result["data"]["row_count"] == 1


def test_execute_query_blocks_write(registry, ctx):
    result = registry.dispatch("execute_query", {"query": "DELETE FROM orders"}, ctx)
    assert result["success"] is False
    assert result["error"]["type"] == "unsafe_statement"
    assert result["error"]["recoverable"] is True


def test_generate_chart_recommends_type(registry, ctx):
    data = [
        {"category": "A", "revenue": 100},
        {"category": "B", "revenue": 200},
        {"category": "C", "revenue": 150},
    ]
    result = registry.dispatch("generate_chart", {"data": data}, ctx)
    assert result["success"] is True
    assert result["data"]["chart"]["type"] in {"bar", "line", "pie", "scatter", "area", "kpi"}


def test_generate_chart_honors_hint(registry, ctx):
    data = [{"m": "2024-05", "v": 1}, {"m": "2024-06", "v": 2}]
    result = registry.dispatch("generate_chart", {"data": data, "chart_type": "pie"}, ctx)
    assert result["success"] is True
    assert result["data"]["chart"]["type"] == "pie"


def test_generate_chart_invalid_args(registry, ctx):
    result = registry.dispatch("generate_chart", {"data": "not-a-list"}, ctx)
    assert result["success"] is False
    assert result["error"]["type"] == "invalid_arguments"


def test_generate_flowchart_er(registry, ctx):
    result = registry.dispatch("generate_flowchart", {"diagram_type": "er"}, ctx)
    assert result["success"] is True
    assert result["data"]["mermaid"].startswith("erDiagram")


def test_generate_flowchart_process(registry, ctx):
    result = registry.dispatch(
        "generate_flowchart", {"diagram_type": "process", "steps": ["Login", "Query", "Render"]}, ctx
    )
    assert result["success"] is True
    assert "flowchart" in result["data"]["mermaid"]


def test_generate_flowchart_bad_type(registry, ctx):
    result = registry.dispatch("generate_flowchart", {"diagram_type": "nope"}, ctx)
    assert result["success"] is True
    assert "error" in result["data"]


def test_explain_data_computes_stats(registry, ctx):
    data = [{"product": "A", "revenue": 10}, {"product": "B", "revenue": 20}]
    result = registry.dispatch("explain_data", {"data": data}, ctx)
    assert result["success"] is True
    assert "2 rows" in result["data"]["explanation"]
    assert result["data"]["statistics"]["count"] == 2


def test_verify_response_detects_missing_artifacts(registry, ctx):
    result = registry.dispatch(
        "verify_response",
        {"user_request": "Show me a bar chart and explain why revenue fell", "produced": {"chart": True, "explanation": False}},
        ctx,
    )
    assert result["success"] is True
    data = result["data"]
    assert data["status"] == "partial"
    assert "explanation" in data["missing_artifacts"]


def test_unknown_tool(registry, ctx):
    result = registry.dispatch("nope", {}, ctx)
    assert result["success"] is False
    assert result["error"]["type"] == "unknown_tool"