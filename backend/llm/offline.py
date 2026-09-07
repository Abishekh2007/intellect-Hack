"""Offline engine.

A zero-API-key fallback that still answers real questions by classifying the
user's intent and running template SQL against the live database. It computes
real results (totals, averages, top-N) and formats them — never fabricates an
answer. This guarantees the demo works even with every API key missing.
"""

from __future__ import annotations

import re
from typing import Any

from db.access_layer import execute_read_only
from security.sql_guard import sanitize_db_error

CASUAL_KEYWORDS = {
    "hi": "hello",
    "hi there": "hello",
    "hello": "hello",
    "hello there": "hello",
    "hey": "hello",
    "hey there": "hello",
    "thank": "thanks",
    "thanks": "thanks",
    "thank you": "thanks",
    "who are you": "identity",
    "what can you do": "capabilities",
    "help": "capabilities",
}

_TREND_RE = re.compile(r"trend|over time|monthly|per month|by month|time series", re.IGNORECASE)
_REVENUE_RE = re.compile(r"revenue|sales|income", re.IGNORECASE)
_CATEGORY_RE = re.compile(r"category|categories", re.IGNORECASE)
_TOP_RE = re.compile(r"top\s+(\d+)", re.IGNORECASE)
_PRODUCT_RE = re.compile(r"product|item|sku", re.IGNORECASE)
_CUSTOMER_RE = re.compile(r"customer|buyer|user", re.IGNORECASE)
_CITY_RE = re.compile(r"city|region|location", re.IGNORECASE)
_STOCK_RE = re.compile(r"stock|inventory|low stock|shortage", re.IGNORECASE)
_ER_RE = re.compile(r"er\s*diagram|relationship|schema\s*diagram", re.IGNORECASE)
_CHART_HINT = re.compile(r"bar chart|line chart|pie chart|scatter", re.IGNORECASE)
_WHY_RE = re.compile(r"why|reason|cause|because", re.IGNORECASE)


def _final(answer: str, **fields: Any) -> dict[str, Any]:
    """A `final` event with every artifact key present.

    The chat route persists exactly these keys, so a missing one is silently
    dropped on reload. Building them in one place keeps every offline exit
    path on the same shape as the agent's.
    """
    event = {
        "type": "final",
        "answer": answer,
        "sql": None,
        "table": None,
        "chart": None,
        "diagram": None,
        "mode": "offline",
    }
    event.update(fields)
    return event


def _detect_chart_hint(prompt: str) -> str | None:
    match = _CHART_HINT.search(prompt)
    if not match:
        return None
    text = match.group(0).lower()
    if "bar" in text:
        return "bar"
    if "line" in text:
        return "line"
    if "pie" in text:
        return "pie"
    if "scatter" in text:
        return "scatter"
    return None


def _resolve_connection(settings, connection=None):
    """The database to answer against, defaulting to the demo one."""
    if connection is not None:
        return connection
    from db.connections import demo_connection

    return demo_connection()


def _schema_of(connection) -> dict[str, Any]:
    from db.schema_discovery import discover_schema_for

    return discover_schema_for(connection)


def _table_names(connection) -> list[str]:
    return [t["name"] for t in _schema_of(connection)["tables"]]


# The row budget every offline template runs under. `_top_n` clamps to the
# same number, so a template can never build SQL its own runner would reject.
OFFLINE_MAX_ROWS = 200


def _run(connection, sql: str, max_rows: int = OFFLINE_MAX_ROWS) -> dict[str, Any]:
    return execute_read_only(sql, connection=connection, max_rows=max_rows)


def _top_n(prompt: str, settings, default: int = 5) -> int:
    """The N from "top N", clamped to the row budget these templates run under.

    Interpolating the number verbatim meant "top 999999 products" built a
    query the SQL guard then rejected for exceeding the ceiling — and the user
    was told the LLM key was missing, which blamed entirely the wrong thing.
    """
    match = _TOP_RE.search(prompt)
    if not match:
        return default
    try:
        n = int(match.group(1))
    except ValueError:
        return default
    ceiling = min(OFFLINE_MAX_ROWS, settings.hard_row_ceiling)
    return max(1, min(n, ceiling))


def _summarize_result(result: dict[str, Any]) -> str:
    columns = result["columns"]
    rows = result["rows"]
    if not rows:
        return "The query returned no rows."
    n = result["row_count"]
    parts = [f"Found {n} row(s)."]
    for row in rows[:5]:
        pair = ", ".join(f"{c}={v}" for c, v in zip(columns, row) if c != "_rank")
        parts.append(f"- {pair}")
    if n > 5:
        parts.append(f"...and {n - 5} more.")
    return "\n".join(parts)


def classify_intent(prompt: str) -> dict[str, Any]:
    """Return an intent descriptor + a chat-only reply (empty if not casual).

    The match is on the whole message. ``startswith`` meant every question
    opening with those letters was answered with a greeting instead of data:
    "highest revenue product" and "history of orders" both began with "hi".
    """
    lowered = prompt.lower().strip().rstrip("!.,?").strip()
    for key, reply_key in CASUAL_KEYWORDS.items():
        if lowered == key:
            replies = {
                "hello": "Hello! I'm DataPilot, your AI data analyst. Ask me about your data, e.g. \"top 5 products by revenue\" or \"show me the ER diagram\".",
                "thanks": "You're welcome! Anything else you'd like to explore in your data?",
                "identity": "I'm DataPilot, an AI agent that turns natural language into database queries, charts and insights.",
                "capabilities": "I can query your database, create charts (bar/line/pie/scatter), draw ER and process diagrams, and explain the results.",
            }
            return {"intent": "casual", "reply": replies[reply_key]}
    return {"intent": "analytical", "reply": ""}


def answer_offline(prompt: str, settings, connection=None) -> dict[str, Any]:
    """Produce a fully-functional answer with no LLM.

    ``connection`` is whichever database the session is pointed at. Without it
    the offline engine always queried the bundled demo file, so a user who had
    just uploaded their own database got answers about someone else's data.

    Returns an SSE-compatible event dict.
    """
    intent = classify_intent(prompt)
    if intent["intent"] == "casual":
        return _final(intent["reply"])

    connection = _resolve_connection(settings, connection)
    p = prompt.lower()
    tables = _table_names(connection)
    table = "orders" if "orders" in tables else (tables[0] if tables else None)
    if table is None:
        return _final("No tables found in the database.")

    chart_hint = _detect_chart_hint(prompt)
    sql = None
    answer = None
    chart = None
    diagram = None

    # --- SQL templates (database-specific but ordered to catch common asks) ---
    if _ER_RE.search(p):
        from viz.mermaid_builder import build_er_diagram

        return _final(
            "Here is the entity-relationship diagram for this database.",
            diagram={"type": "er", "mermaid": build_er_diagram(_schema_of(connection))},
        )

    if _TREND_RE.search(p) and _REVENUE_RE.search(p):
        sql = "SELECT substr(order_date,1,7) AS month, SUM(oi.quantity*oi.unit_price) AS revenue FROM orders o JOIN order_items oi ON o.order_id=oi.order_id WHERE o.status='completed' GROUP BY month ORDER BY month LIMIT 12"
        answer = "Monthly revenue trend."
        chart = chart_hint or "line"
    elif _TOP_RE.search(p) and _REVENUE_RE.search(p):
        n = _top_n(p, settings)
        sql = f"SELECT p.name AS product, SUM(oi.quantity*oi.unit_price) AS revenue FROM order_items oi JOIN products p ON oi.product_id=p.product_id JOIN orders o ON oi.order_id=o.order_id WHERE o.status='completed' GROUP BY p.name ORDER BY revenue DESC LIMIT {n}"
        answer = f"Top {n} products by revenue."
        chart = chart_hint or "bar"
    elif _REVENUE_RE.search(p) and _CATEGORY_RE.search(p):
        sql = "SELECT p.category, SUM(oi.quantity*oi.unit_price) AS revenue FROM order_items oi JOIN products p ON oi.product_id=p.product_id JOIN orders o ON oi.order_id=o.order_id WHERE o.status='completed' GROUP BY p.category ORDER BY revenue DESC"
        answer = "Revenue by product category."
        # Leave the type open: a "breakdown"/"share" question earns a pie here,
        # a plain "by category" comparison stays a bar.
        chart = chart_hint
    elif _REVENUE_RE.search(p) and _CUSTOMER_RE.search(p) and _TOP_RE.search(p):
        n = _top_n(p, settings)
        sql = f"SELECT c.name AS customer, SUM(oi.quantity*oi.unit_price) AS spent FROM orders o JOIN order_items oi ON o.order_id=oi.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE o.status='completed' GROUP BY c.name ORDER BY spent DESC LIMIT {n}"
        answer = f"Top {n} customers by spend."
        chart = chart_hint or "bar"
    elif _CITY_RE.search(p) and _REVENUE_RE.search(p):
        sql = "SELECT c.city, SUM(oi.quantity*oi.unit_price) AS revenue FROM orders o JOIN order_items oi ON o.order_id=oi.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE o.status='completed' GROUP BY c.city ORDER BY revenue DESC"
        answer = "Revenue by customer city."
        chart = chart_hint
    elif _STOCK_RE.search(p):
        sql = "SELECT p.name AS product, p.stock AS stock_level FROM products p ORDER BY p.stock ASC LIMIT 10"
        answer = "Products with lowest stock."
        chart = chart_hint or "bar"
    elif _TOP_RE.search(p) and _PRODUCT_RE.search(p):
        n = _top_n(p, settings)
        sql = f"SELECT p.name AS product, COUNT(oi.order_item_id) AS times_ordered FROM order_items oi JOIN products p ON oi.product_id=p.product_id GROUP BY p.name ORDER BY times_ordered DESC LIMIT {n}"
        answer = f"Top {n} most-ordered products."
        chart = chart_hint or "bar"
    elif _TREND_RE.search(p) or re.search(r"by\s+month|monthly|per\s+month", p):
        sql = "SELECT substr(o.order_date,1,7) AS month, COUNT(DISTINCT o.order_id) AS orders FROM orders o WHERE o.status='completed' GROUP BY month ORDER BY month LIMIT 12"
        answer = "Monthly order counts."
        chart = chart_hint or "line"
    else:
        # Default: show a small overview.
        sql = "SELECT COUNT(*) AS order_count, COUNT(DISTINCT customer_id) AS customers FROM orders"
        answer = "Here is a quick overview of your orders table."
        chart = "kpi"

    try:
        result = _run(connection, sql)
    except Exception as exc:  # noqa: BLE001
        return _final(
            "I couldn't run that query against this database. The templates in "
            "offline mode assume the demo schema — add an LLM API key for "
            "questions about your own tables, or run SQL from the Data tab.",
            sql=sql,
            error=sanitize_db_error(exc),
        )

    from viz.recommender import build_chart_spec

    columns, rows = result["columns"], result["rows"]
    chart_spec = None
    if rows:
        chart_spec = build_chart_spec(columns, rows, chart_type=chart, intent=prompt)
        chart_spec["title"] = answer
    summary = _summarize_result(result)
    return _final(
        f"{answer}\n\n{summary}",
        sql=result["sql"],
        chart=chart_spec,
        diagram=diagram,
        # The rows themselves. Offline answers used to omit this, so the chat
        # described a result the user could never see in a table — and the
        # reload path had nothing to restore.
        table={
            "columns": columns,
            "rows": rows,
            "row_count": result.get("row_count", len(rows)),
            "truncated": result.get("truncated", False),
        },
    )