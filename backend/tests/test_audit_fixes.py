"""Regression tests for the defects found in the code audit.

Each test names the behaviour that was wrong and asserts the corrected one, so
a future refactor that reintroduces the bug fails here rather than in a demo.
"""

from __future__ import annotations

import sqlite3

import pytest

from db.access_layer import execute_read_only


# --- SQL guard -------------------------------------------------------------

def test_a_subquery_limit_does_not_satisfy_the_row_ceiling():
    """The cap must bound the *result*, not any LIMIT anywhere in the tree.

    `_detect_limit` walked the whole AST, so a LIMIT inside a subquery counted
    as the query's row cap and no outer LIMIT was injected — an unbounded
    result set reached both the browser and the model.
    """
    from security.sql_guard import validate_sql

    result = validate_sql(
        "SELECT * FROM (SELECT * FROM products LIMIT 5) t",
        enforce_limit=True,
        max_rows=1000,
    )
    assert result.valid, result.error_message
    assert result.sql.rstrip().upper().endswith("LIMIT 1000")


def test_scalar_functions_sharing_a_keyword_name_are_allowed():
    """REPLACE() is a string function; blocking it rejected valid read-only SQL."""
    from security.sql_guard import validate_sql

    result = validate_sql(
        "SELECT REPLACE(name, 'a', 'b') AS n FROM products", max_rows=500
    )
    assert result.valid, result.error_message


def test_a_semicolon_inside_a_string_literal_is_not_a_statement_break():
    from security.sql_guard import validate_sql

    result = validate_sql("SELECT * FROM products WHERE name = 'a;b'", max_rows=500)
    assert result.valid, result.error_message


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM products",
        "DROP TABLE products",
        "UPDATE products SET name='x'",
        "INSERT INTO products VALUES (1)",
        "SELECT 1; DROP TABLE products",
        "SELECT 1 -- c\n; DELETE FROM products",
        "SELECT * FROM products; PRAGMA table_info(x)",
    ],
)
def test_write_statements_are_still_blocked(sql):
    """The guard was loosened in two places; prove it did not go soft."""
    from security.sql_guard import validate_sql

    assert not validate_sql(sql, max_rows=500).valid, sql


def test_a_cte_keeps_its_definition_after_the_limit_rewrite():
    from security.sql_guard import validate_sql

    result = validate_sql(
        "WITH t AS (SELECT * FROM products) SELECT * FROM t", max_rows=500
    )
    assert result.valid, result.error_message
    assert "WITH" in result.sql.upper()
    assert "LIMIT 500" in result.sql.upper()


def test_error_messages_do_not_leak_posix_paths_or_passwords():
    from security.sql_guard import sanitize_db_error

    assert "/srv" not in sanitize_db_error(Exception("cannot open /srv/app/data/x.db"))
    assert "secret" not in sanitize_db_error(
        Exception("failed: postgresql://user:secret@host:5432/db")
    )
    # An ordinary SQL error still reads naturally.
    assert (
        sanitize_db_error(Exception("no such column: prodcut"))
        == "no such column: prodcut"
    )


# --- PII masking -----------------------------------------------------------

def test_a_sensitive_column_is_masked_whatever_it_contains():
    """Column-name detection must not defer to the value regexes.

    A `password` column holding "hunter2" matches no card/SSN/e-mail pattern,
    so it was renamed `password_redacted` and then handed over in full.
    """
    from security.pii import redact_rows

    columns, rows = redact_rows(["password"], [["hunter2"]])
    assert columns == ["password_redacted"]
    assert rows == [["***"]]


def test_pii_in_an_innocently_named_column_is_still_caught():
    """The value-pattern layer only ever ran on columns layer 1 had caught."""
    from security.pii import redact_rows

    assert redact_rows(["notes"], [["reach me at a@b.com"]])[1] == [["***"]]


def test_content_scanning_does_not_mask_ordinary_identifiers():
    """The broad scan must not fire on SKUs, order numbers, dates or money."""
    from security.pii import redact_rows

    columns = ["sku", "order_id", "order_date", "revenue"]
    rows = [["1234567890", 1234567890, "2024-03-11", 12345.67]]
    assert redact_rows(columns, rows)[1] == rows


# --- Access layer ----------------------------------------------------------

def test_an_empty_result_still_reports_its_columns():
    """Columns came from row[0], so a zero-row result rendered headerless."""
    result = execute_read_only("SELECT product_id, name FROM products WHERE 1=0")
    assert result["columns"] == ["product_id", "name"]
    assert result["rows"] == []


# --- File ingestion --------------------------------------------------------

def test_uploaded_numeric_columns_are_typed_as_numbers():
    """Every column used to land as TEXT, so "9" sorted above "100"."""
    from db.file_ingest import ingest_upload

    conn = sqlite3.connect(":memory:")
    ingest_upload(
        "sales.csv", b"product,units,price\nMouse,10,899.5\nKeyboard,4,2499.0\n", conn
    )
    types = {r[1]: r[2] for r in conn.execute('PRAGMA table_info("sales")')}
    assert types == {"product": "TEXT", "units": "INTEGER", "price": "REAL"}
    ordered = conn.execute('SELECT product FROM "sales" ORDER BY units DESC').fetchall()
    assert [r[0] for r in ordered] == ["Mouse", "Keyboard"]


def test_duplicate_headers_do_not_break_table_creation():
    """Sanitising collapses "total sales" and "total-sales" onto one name."""
    from db.file_ingest import ingest_upload

    info = ingest_upload(
        "dup.csv", b"total sales,total-sales\n1,2\n", sqlite3.connect(":memory:")
    )
    assert info["columns"] == ["total_sales", "total_sales_2"]


# --- ER diagram ------------------------------------------------------------

def test_er_diagram_is_valid_mermaid_and_points_the_right_way():
    """The old builder emitted a stray closing brace, so nothing ever rendered,
    and put the crow's foot on the parent, reversing every relationship."""
    from db.schema_discovery import relationships_as_mermaid_er

    schema = {
        "tables": [
            {
                "name": "orders",
                "columns": [{"name": "order_id", "type": "INTEGER", "pk": True}],
                "primary_keys": ["order_id"],
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "references_table": "customers",
                        "references_column": "customer_id",
                    }
                ],
            },
            {
                "name": "customers",
                "columns": [{"name": "customer_id", "type": "INTEGER", "pk": True}],
                "primary_keys": ["customer_id"],
                "foreign_keys": [],
            },
        ]
    }
    mermaid = relationships_as_mermaid_er(schema)

    # One customer has many orders, so customers sits on the "||" side.
    assert "customers ||--o{ orders" in mermaid
    # No relationship line may end with a brace: that is the parse error.
    for line in mermaid.splitlines():
        if "||--o{" in line:
            assert not line.rstrip().endswith("}"), line
    # Every entity block that opens also closes.
    assert mermaid.count("{") - mermaid.count("||--o{") == mermaid.count("}")


# --- Agent + offline routing ----------------------------------------------

@pytest.mark.parametrize(
    "question",
    [
        "help me find the top 5 products by revenue",
        "hey what is our revenue?",
        "highest revenue product",
        "history of orders",
        "hello world table row count",
    ],
)
def test_a_greeting_prefix_does_not_swallow_a_real_question(question):
    """A prefix match sent these to the canned reply, never to the database."""
    from agent.loop import _is_conversational
    from llm.offline import classify_intent

    assert _is_conversational(question) is None, question
    assert classify_intent(question)["intent"] == "analytical", question


@pytest.mark.parametrize("greeting", ["hi", "hello", "Thanks!", "what can you do", "hey there"])
def test_actual_greetings_still_short_circuit(greeting):
    from agent.loop import _is_conversational

    assert _is_conversational(greeting), greeting


def test_offline_answers_carry_the_rows_they_describe(settings):
    """The offline `final` event omitted `table`, so the chat described a
    result the user could never see and a reload restored nothing."""
    from llm.offline import answer_offline

    event = answer_offline("top 3 products by revenue", settings)
    assert event["table"] and event["table"]["columns"]
    assert len(event["table"]["rows"]) == 3
    assert set(event) >= {"sql", "table", "chart", "diagram", "mode"}


def test_offline_top_n_is_clamped_to_the_row_ceiling(settings):
    """An absurd N built SQL the guard then rejected, and the user was told the
    LLM key was missing — which was not the problem."""
    from llm.offline import answer_offline

    from llm.offline import OFFLINE_MAX_ROWS

    event = answer_offline("top 999999 products by revenue", settings)
    assert event["table"] is not None
    assert f"LIMIT {OFFLINE_MAX_ROWS}" in event["sql"]


def test_every_offline_exit_path_has_the_full_artifact_shape(settings):
    """A missing key is silently dropped when the chat route persists a turn."""
    from llm.offline import answer_offline

    required = {"type", "answer", "sql", "table", "chart", "diagram", "mode"}
    for prompt in ("hi", "show me the ER diagram", "monthly revenue trend"):
        assert set(answer_offline(prompt, settings)) >= required, prompt


# --- Provider failover -----------------------------------------------------

def test_all_providers_failed_surfaces_where_the_loop_can_catch_it():
    """stream_tool_calls is a generator: calling it raises nothing, so the old
    try/except around the *call* caught nothing and the error escaped into the
    SSE response as an unhandled exception."""
    from llm.base import AllProvidersFailed
    from llm.failover import FailoverProvider

    events = FailoverProvider([]).stream_tool_calls([], [], "")  # must not raise
    with pytest.raises(AllProvidersFailed):
        list(events)


def test_failover_does_not_replay_text_a_provider_already_streamed():
    """Failing over mid-stream duplicated the partial answer on screen."""
    from llm.base import AllProvidersFailed, ProviderError
    from llm.failover import FailoverProvider

    class HalfStream:
        name = "half"

        def stream_tool_calls(self, messages, tools, system_prompt):
            yield {"type": "text", "text": "partial "}
            raise ProviderError("boom", "died mid-stream")

    class Healthy:
        name = "healthy"

        def stream_tool_calls(self, messages, tools, system_prompt):
            yield {"type": "text", "text": "full answer"}

    collected = []
    with pytest.raises(AllProvidersFailed):
        for event in FailoverProvider([HalfStream(), Healthy()]).stream_tool_calls([], [], ""):
            collected.append(event["text"])
    assert collected == ["partial "]


def test_failover_still_switches_when_nothing_was_emitted():
    """A provider that fails before its first event must fail over silently."""
    from llm.base import ProviderError
    from llm.failover import FailoverProvider

    class DeadOnArrival:
        name = "dead"

        def stream_tool_calls(self, messages, tools, system_prompt):
            raise ProviderError("auth", "bad key")
            yield  # pragma: no cover - makes this a generator

    class Healthy:
        name = "healthy"

        def stream_tool_calls(self, messages, tools, system_prompt):
            yield {"type": "text", "text": "full answer"}

    events = list(
        FailoverProvider([DeadOnArrival(), Healthy()]).stream_tool_calls([], [], "")
    )
    assert [e["text"] for e in events] == ["full answer"]


# --- Session context -------------------------------------------------------

def test_trace_does_not_share_one_list_across_sessions():
    """A mutable ContextVar default is created once and shared by every context
    that never calls set(), so events leaked between unrelated sessions."""
    from memory.session_context import SessionScope, get_current_trace, trace

    with SessionScope("session-a"):
        trace("a")
        assert len(get_current_trace()) == 1
    with SessionScope("session-b"):
        assert get_current_trace() == []
