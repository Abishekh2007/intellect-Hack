"""Tests for the agent loop using a fake LLM (no network, no API keys)."""

from __future__ import annotations

import asyncio

import pytest

from agent.loop import DataPilotAgent
from tests.fake_llm import FailingChatModel, ScriptedChatModel, ToolCallingModel

# The agent builds providers from settings; we inject a fake failover by
# monkeypatching DataPilotAgent.failover after construction.


async def _collect(agen):
    return [event async for event in agen]


@pytest.mark.asyncio
async def test_conversational_short_circuit_no_llm(settings):
    agent = DataPilotAgent(settings)
    agent.failover = None  # even with no provider, greetings must work
    events = await _collect(agent.stream_turn("hello", "s1"))
    final = [e for e in events if e.get("type") == "final"]
    assert final
    assert "DataPilot" in final[0]["answer"]


@pytest.mark.asyncio
async def test_offline_engine_answers_without_keys(settings):
    agent = DataPilotAgent(settings)
    agent.failover = None
    events = await _collect(agent.stream_turn("top 5 products by revenue", "s2"))
    final = [e for e in events if e.get("type") == "final"][0]
    assert final["mode"] == "offline"
    assert "Monitor" in final["answer"]
    assert final["chart"] is not None


@pytest.mark.asyncio
async def test_offline_er_diagram(settings):
    agent = DataPilotAgent(settings)
    agent.failover = None
    events = await _collect(agent.stream_turn("show me the ER diagram", "s3"))
    final = [e for e in events if e.get("type") == "final"][0]
    assert final["diagram"] is not None
    assert final["diagram"]["mermaid"].startswith("erDiagram")


@pytest.mark.asyncio
async def test_agent_executes_tool_turn_with_scripted_llm(settings, monkeypatch):
    script = [
        {"type": "tool_call", "name": "get_schema", "arguments": {"scope": "full"}},
        {"type": "text", "text": "Let me check the schema first."},
    ]
    fake = ScriptedChatModel(script)
    agent = DataPilotAgent(settings)
    agent.failover = FakeFailover(fake)

    events = await _collect(agent.stream_turn("What tables exist?", "s4"))
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "get_schema"
    # Scripted model produces no final answer -> fallback used.
    finals = [e for e in events if e.get("type") == "final"]
    assert finals


@pytest.mark.asyncio
async def test_agent_full_query_chart_flow(settings, monkeypatch):
    """Verify the whole loop: schema -> query -> chart with a tool-calling fake."""
    behavior = {
        "what were the top products by revenue?".lower(): [
            {"type": "tool_call", "name": "execute_query", "arguments": {"query": "SELECT p.name AS product, SUM(oi.quantity*oi.unit_price) AS revenue FROM order_items oi JOIN products p ON oi.product_id=p.product_id JOIN orders o ON oi.order_id=o.order_id GROUP BY p.name ORDER BY revenue DESC LIMIT 5"}},
        ],
    }
    fake = ToolCallingModel(behavior)
    agent = DataPilotAgent(settings)
    agent.failover = FakeFailover(fake)

    events = await _collect(agent.stream_turn("What were the top products by revenue?", "s5"))
    types = [e.get("type") for e in events]
    assert "sql" in types
    assert "table" in types
    finals = [e for e in events if e.get("type") == "final"]
    assert finals


@pytest.mark.asyncio
async def test_agent_handles_provider_outage_gracefully(settings):
    fake = FailingChatModel("auth_error", "bad key")
    agent = DataPilotAgent(settings)
    agent.failover = FakeFailover(fake)
    events = await _collect(agent.stream_turn("show revenue by category", "s6"))
    # Should produce an error event, not crash.
    assert any(e.get("type") == "error" for e in events)


@pytest.mark.asyncio
async def test_multi_turn_memory(settings):
    agent = DataPilotAgent(settings)
    agent.failover = None
    await _collect(agent.stream_turn("top 3 products", "s7"))
    # Second turn still works (memory intact).
    events = await _collect(agent.stream_turn("and their prices", "s7"))
    assert events


class FakeFailover:
    """Minimal stand-in for FailoverProvider that wraps a fake model."""

    def __init__(self, model):
        self.model = model

    def stream_tool_calls(self, messages, tools, system_prompt):
        yield from self.model.stream_tool_calls(messages, tools, system_prompt)