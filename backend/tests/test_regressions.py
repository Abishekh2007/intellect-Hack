"""Regression tests for defects found in the Phase 1 audit.

Each test here pins a behaviour that was previously broken. They are grouped by
the defect they cover so a failure names the thing that regressed.
"""

from __future__ import annotations

import json

import pytest

from db.access_layer import execute_read_only
from llm.providers import messages_to_openai
from store import result_store, session_store
from viz.recommender import build_chart_spec, recommend_chart


# --- BUG-01: turn context must survive provider conversion -----------------

def test_system_message_in_history_is_not_dropped():
    """A system message mid-history is context, not configuration.

    It used to be skipped outright, silently discarding the previous result
    that follow-up questions resolve against.
    """
    messages = [
        {"role": "user", "content": "top 5 products"},
        {"role": "system", "content": "Previous query result: product=Monitor, revenue=900"},
    ]
    out = messages_to_openai(messages)
    assert len(out) == 2
    assert "Monitor" in out[1]["content"]


def test_last_result_reaches_the_model_via_system_prompt(settings):
    """The agent's own channel for follow-up context must actually arrive."""
    from agent.loop import DataPilotAgent
    from memory.conversation_memory import ConversationMemory

    memory = ConversationMemory(6)
    memory.set_last_result(
        {"columns": ["product", "revenue"], "rows": [["Monitor", 900]], "row_count": 1}
    )
    agent = DataPilotAgent(settings)
    captured: dict[str, str] = {}

    class CapturingFailover:
        def stream_tool_calls(self, messages, tools, system_prompt):
            captured["system_prompt"] = system_prompt
            yield {"type": "text", "text": "ok"}
            yield {"type": "done"}

    agent.failover = CapturingFailover()

    async def run():
        return [e async for e in agent._process("chart those", memory)]

    import asyncio

    asyncio.run(run())
    assert "Monitor" in captured["system_prompt"]


# --- BUG-07: tool results must not be encoded twice ------------------------

def test_tool_content_is_not_double_encoded():
    payload = json.dumps({"columns": ["a"], "rows": [[1]]})
    out = messages_to_openai([{"role": "tool", "tool_call_id": "c1", "content": payload}])
    # Parses in one hop back to the original object, not to another string.
    assert json.loads(out[0]["content"]) == {"columns": ["a"], "rows": [[1]]}


def test_non_string_tool_content_still_serialized():
    out = messages_to_openai([{"role": "tool", "tool_call_id": "c1", "content": {"a": 1}}])
    assert json.loads(out[0]["content"]) == {"a": 1}


# --- BUG-02: the final event must carry what the turn produced -------------

@pytest.mark.asyncio
async def test_final_event_carries_artifacts_for_persistence(settings):
    """Artifacts absent from `final` are lost on reload — the chat route
    persists exactly these fields."""
    from agent.loop import DataPilotAgent
    from tests.fake_llm import ToolCallingModel
    from tests.test_agent import FakeFailover

    sql = "SELECT name AS product, price FROM products ORDER BY price DESC LIMIT 3"
    fake = ToolCallingModel(
        {"top 3 by price": [{"type": "tool_call", "name": "execute_query", "arguments": {"query": sql}}]}
    )
    agent = DataPilotAgent(settings)
    agent.failover = FakeFailover(fake)

    events = [e async for e in agent.stream_turn("top 3 by price", "reg-artifacts")]
    final = [e for e in events if e.get("type") == "final"][0]

    assert final["sql"], "final event lost the SQL"
    assert final["table"], "final event lost the result table"
    assert final["table"]["rows"], "persisted table has no rows"


# --- BUG-03: a reloaded thread must read in the order it happened ----------

def test_messages_replay_in_insertion_order():
    session_id = session_store.create_session("ordering")
    try:
        # Same wall-clock second: created_at alone cannot separate these.
        session_store.add_message(session_id, "user", "question", {})
        session_store.add_message(session_id, "assistant", "answer", {})
        session_store.add_message(session_id, "user", "follow-up", {})

        roles = [m["role"] for m in session_store.list_messages(session_id)]
        contents = [m["content"] for m in session_store.list_messages(session_id)]
        assert roles == ["user", "assistant", "user"]
        assert contents == ["question", "answer", "follow-up"]
        # seq must actually be populated — created_at ties would otherwise be
        # resolved by rowid, which is luck rather than ordering.
        seqs = [m["seq"] for m in session_store.list_messages(session_id)]
        assert seqs == sorted(seqs) and len(set(seqs)) == 3
    finally:
        session_store.delete_session(session_id)


def test_chat_route_persists_the_question_before_the_answer():
    """The user message used to be written after the turn finished, so a
    reloaded thread showed the answer above the question that prompted it."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    session_id = client.post("/api/sessions", json={"title": "order"}).json()["session_id"]
    try:
        client.post("/api/chat", json={"message": "hello", "session_id": session_id})
        roles = [m["role"] for m in client.get(f"/api/sessions/{session_id}").json()["messages"]]
        assert roles[:2] == ["user", "assistant"], roles
    finally:
        client.delete(f"/api/sessions/{session_id}")


# --- BUG-05: all four required chart types must be reachable ---------------

def test_all_required_chart_types_are_auto_reachable():
    """The brief requires bar, line and pie (scatter as bonus). None of these
    may depend on the user naming the chart type."""
    reachable = set()

    # Ranking: category + measure.
    reachable.add(recommend_chart(["product", "revenue"], [["A", 30], ["B", 20], ["C", 10]]))
    # Trend: date + measure.
    reachable.add(
        recommend_chart(["month", "revenue"], [[f"2024-0{i}", i * 10] for i in range(1, 7)])
    )
    # Share of a whole: needs the question, not just the shape.
    reachable.add(
        recommend_chart(
            ["category", "revenue"],
            [["Electronics", 500], ["Books", 300], ["Toys", 200]],
            intent="what is the revenue breakdown by category?",
        )
    )
    # Correlation: two measures, no label column.
    reachable.add(recommend_chart(["price", "units_sold"], [[i, i * 2] for i in range(1, 12)]))

    assert {"bar", "line", "pie", "scatter"}.issubset(reachable)


def test_share_intent_alone_does_not_force_a_bad_pie():
    """Intent only unlocks pie; the data still has to suit one."""
    # Too many slices to read.
    many = [[f"cat{i}", i] for i in range(1, 15)]
    assert recommend_chart(["category", "n"], many, intent="show the distribution") != "pie"

    # Negative values have no meaningful wedge area.
    negative = [["A", 30], ["B", -20], ["C", 10]]
    assert recommend_chart(["category", "profit"], negative, intent="profit breakdown") != "pie"

    # A trend stays a trend even when asked for as a "split".
    dated = [[f"2024-0{i}", i * 10] for i in range(1, 7)]
    assert recommend_chart(["month", "revenue"], dated, intent="monthly split") == "line"


def test_ranking_question_still_gets_a_bar():
    """"Top N" is a comparison, not a partition — regression guard for the
    pie rule over-reaching."""
    rows = [["Monitor", 900], ["Keyboard", 500], ["Mouse", 300]]
    assert recommend_chart(["product", "revenue"], rows, intent="top 3 products by revenue") == "bar"


def test_scatter_spec_puts_both_measures_on_the_axes():
    rows = [[i, i * 2] for i in range(1, 12)]
    spec = build_chart_spec(["price", "units_sold"], rows)
    assert spec["type"] == "scatter"
    assert spec["x_key"] == "price"
    assert spec["y_key"] == "units_sold"


def test_explicit_hint_still_overrides_everything():
    rows = [["A", 100], ["B", 200]]
    assert build_chart_spec(["cat", "val"], rows, chart_type="pie")["type"] == "pie"


# --- BUG-06: results stay server-side, referenced by id --------------------

def _registry_and_ctx(settings):
    from tools.builder import build_registry

    return build_registry(), {"settings": settings}


def test_execute_query_returns_a_reference_not_a_row_dump(settings):
    registry, ctx = _registry_and_ctx(settings)
    payload = registry.dispatch(
        "execute_query", {"query": "SELECT name, price FROM products"}, ctx
    )["data"]
    assert "result_id" in payload
    assert "rows" not in payload, "raw rows are back in the model-facing payload"
    assert payload[result_store.PREVIEW_KEY], "the model needs some rows to reason about shape"
    assert len(payload[result_store.PREVIEW_KEY]) <= result_store.PREVIEW_ROWS


def test_charts_cover_the_whole_result_not_just_the_preview(settings):
    """The point of the result store: the chart is built from rows the model
    never saw, so a wide result is not silently truncated to the preview."""
    registry, ctx = _registry_and_ctx(settings)
    payload = registry.dispatch(
        "execute_query",
        {"query": "SELECT p.name AS product, c.city, p.price FROM products p CROSS JOIN customers c"},
        ctx,
    )["data"]
    stored = result_store.get(payload["result_id"])
    assert stored["row_count"] > len(payload[result_store.PREVIEW_KEY]), "test needs a result past the preview"

    chart = registry.dispatch(
        "generate_chart", {"result_id": payload["result_id"]}, ctx
    )["data"]["chart"]
    assert len(chart["rows"]) == stored["row_count"]

    stats = registry.dispatch(
        "explain_data", {"result_id": payload["result_id"]}, ctx
    )["data"]["statistics"]
    assert stats["count"] == stored["row_count"]


def test_a_stale_result_id_fails_loudly(settings):
    """Silently charting nothing would look like a working answer."""
    registry, ctx = _registry_and_ctx(settings)
    for tool in ("generate_chart", "explain_data"):
        result = registry.dispatch(tool, {"result_id": "res_missing"}, ctx)
        assert result["success"] is False
        assert result["error"]["type"] == "unknown_result_id"
        assert result["error"]["recoverable"] is True


def test_inline_data_still_works_without_a_result_id(settings):
    """Not every chart comes from a query."""
    registry, ctx = _registry_and_ctx(settings)
    result = registry.dispatch(
        "generate_chart", {"data": [{"a": "x", "b": 1}, {"a": "y", "b": 2}]}, ctx
    )
    assert result["success"] is True
    assert len(result["data"]["chart"]["rows"]) == 2


# --- GAP-05: explanations are narrated but still grounded ------------------

def test_explanation_falls_back_to_computed_prose_without_a_provider(settings):
    registry, ctx = _registry_and_ctx(settings)
    data = [{"product": "A", "revenue": 10}, {"product": "B", "revenue": 20}]
    out = registry.dispatch("explain_data", {"data": data}, ctx)["data"]
    assert out["source"] == "computed"
    assert "2 rows" in out["explanation"]


def test_a_failing_provider_never_breaks_the_explanation(settings):
    """The narration is a nice-to-have; the computed summary is the contract."""
    registry, ctx = _registry_and_ctx(settings)

    class ExplodingLLM:
        def stream_tool_calls(self, *a, **kw):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    ctx["llm"] = ExplodingLLM()
    out = registry.dispatch(
        "explain_data", {"data": [{"product": "A", "revenue": 10}]}, ctx
    )["data"]
    assert out["source"] == "computed"
    assert out["explanation"]


def test_statistics_keep_label_to_measure_pairings(settings):
    """Per-column stats alone lose which row a figure belongs to, so the model
    can report the top number but not what earned it."""
    registry, ctx = _registry_and_ctx(settings)
    data = [{"product": "A", "revenue": 30}, {"product": "B", "revenue": 20}]
    stats = registry.dispatch("explain_data", {"data": data}, ctx)["data"]["statistics"]
    assert stats["leading_rows"][0] == {"product": "A", "revenue": 30}
    assert stats["column_stats"]["revenue"]["sum"] == 50


def test_a_column_named_count_does_not_clobber_the_row_count(settings):
    """Per-column stats live under `column_stats`, not beside the row count.

    Writing them onto the top level meant `SELECT category, COUNT(*) AS count`
    — an everyday query — replaced the integer row count with a stats dict,
    and the summary read "The result contains {'sum': 14.0, ...} rows."
    """
    registry, ctx = _registry_and_ctx(settings)
    data = [{"category": "Books", "count": 10}, {"category": "Toys", "count": 4}]
    out = registry.dispatch("explain_data", {"data": data}, ctx)["data"]
    assert out["statistics"]["count"] == 2
    assert out["statistics"]["column_stats"]["count"]["sum"] == 14
    assert "The result contains 2 rows." in out["grounded_summary"]


def test_statistics_include_negative_values(settings):
    """`str.isdigit()` rejects "-5", so losses were dropped before summing."""
    registry, ctx = _registry_and_ctx(settings)
    data = [{"month": "2024-01", "profit": -500}, {"month": "2024-02", "profit": 1500}]
    stats = registry.dispatch("explain_data", {"data": data}, ctx)["data"]["statistics"]
    assert stats["column_stats"]["profit"] == {
        "sum": 1000.0,
        "avg": 500.0,
        "min": -500.0,
        "max": 1500.0,
    }


# --- BUG-09: the agent remembers what the sidebar shows --------------------

def test_memory_is_rebuilt_from_storage_after_a_restart(settings):
    """A reload creates a fresh agent; the conversation must survive it."""
    from agent.loop import DataPilotAgent

    session_id = session_store.create_session("rehydrate")
    try:
        session_store.add_message(session_id, "user", "top products by revenue", {})
        session_store.add_message(
            session_id,
            "assistant",
            "Here are the top products.",
            {"table": {"columns": ["product", "revenue"], "rows": [["Monitor", 900]], "row_count": 1}},
        )

        agent = DataPilotAgent(settings)  # cold, as after a restart
        memory = agent._hydrate_memory(session_id, "and their stock levels")

        assert [m["role"] for m in memory.get_messages()] == ["user", "assistant"]
        assert "Monitor" in memory.last_result_context()
    finally:
        session_store.delete_session(session_id)


def test_hydration_does_not_duplicate_the_current_question(settings):
    """The chat route persists the question before the turn runs."""
    from agent.loop import DataPilotAgent

    session_id = session_store.create_session("dupe")
    try:
        session_store.add_message(session_id, "user", "how many orders?", {})
        agent = DataPilotAgent(settings)
        memory = agent._hydrate_memory(session_id, "how many orders?")
        assert memory.get_messages() == []
    finally:
        session_store.delete_session(session_id)


# --- BUG-10: shared links outlive a restart --------------------------------

def test_shares_are_persisted_not_held_in_memory():
    """A link handed out in a demo must still resolve later."""
    share_id = session_store.create_share("chart", "Revenue", {"type": "bar"})
    fetched = session_store.get_share(share_id)
    assert fetched is not None
    assert fetched["title"] == "Revenue"
    assert fetched["payload"] == {"type": "bar"}
    assert session_store.get_share("does-not-exist") is None


# --- BUG-08: PII masking must apply to every query -------------------------

def test_sensitive_columns_are_masked_on_the_way_out(settings):
    """Masking belongs at the access layer, so it covers the browser and the
    LLM alike — not just one UI path."""
    result = execute_read_only(
        "SELECT name, email FROM customers LIMIT 3", db_path=settings.db_path
    )
    assert "email_redacted" in result["columns"]
    emails = [row[result["columns"].index("email_redacted")] for row in result["rows"]]
    assert all(v == "***" for v in emails), emails
    # Non-sensitive columns are untouched.
    names = [row[result["columns"].index("name")] for row in result["rows"]]
    assert any(n and n != "***" for n in names)
