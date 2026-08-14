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
from db.engine import create_readonly_connection
from db.schema_discovery import discover_schema

CASUAL_KEYWORDS = {
    "hi": "hello",
    "hello": "hello",
    "hey": "hello",
    "thank": "thanks",
    "thanks": "thanks",
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


def _table_names(settings) -> list[str]:
    conn = create_readonly_connection(settings.db_path)
    try:
        schema = discover_schema(conn)
        return [t["name"] for t in schema["tables"]]
    finally:
        conn.close()


def _run(settings, sql: str, max_rows: int = 200) -> dict[str, Any]:
    return execute_read_only(sql, db_path=settings.db_path, max_rows=max_rows)


def _summarize_result(result: dict[str, Any]) -> str:
    columns = result["columns"]
    rows = result["rows"]
    if not rows:
        return "The query returned no rows."
    n = result["row_count"]
    parts = [f"Found {n} row(s)."]
    for i, row in enumerate(rows[:5]):
        pair = ", ".join(f"{c}={v}" for c, v in zip(columns, row) if c != "_rank")
        parts.append(f"- {pair}")
    if n > 5:
        parts.append(f"...and {n - 5} more.")
    return "\n".join(parts)


def classify_intent(prompt: str) -> dict[str, Any]:
    """Return an intent descriptor + a chat-only reply (empty if not casual)."""
    lowered = prompt.lower().strip()
    for key, reply_key in CASUAL_KEYWORDS.items():
        if lowered == key or lowered.startswith(key):
            replies = {
                "hello": "Hello! I'm DataPilot, your AI data analyst. Ask me about your data, e.g. \"top 5 products by revenue\" or \"show me the ER diagram\".",
                "thanks": "You're welcome! Anything else you'd like to explore in your data?",
                "identity": "I'm DataPilot, an AI agent that turns natural language into database queries, charts and insights.",
                "capabilities": "I can query your database, create charts (bar/line/pie/scatter), draw ER and process diagrams, and explain the results.",
            }
            return {"intent": "casual", "reply": replies[reply_key]}
    return {"intent": "analytical", "reply": ""}


def answer_offline(prompt: str, settings) -> dict[str, Any]:
    """Produce a fully-functional answer with no LLM.

    Returns an SSE-compatible event dict or None if no match.
    """
    intent = classify_intent(prompt)
    if intent["intent"] == "casual":
        return {"type": "final", "answer": intent["reply"], "sql": None, "chart": None, "diagram": None, "mode": "offline"}

    p = prompt.lower()
    tables = _table_names(settings)
    has_custom = any(not t.startswith(("customers", "products", "orders", "inventory")) for t in tables)
    table = "orders" if "orders" in tables else (tables[0] if tables else None)
    if table is None:
        return {"type": "final", "answer": "No tables found in the database.", "mode": "offline"}

    chart_hint = _detect_chart_hint(prompt)
    sql = None
    answer = None
    chart = None
    diagram = None

    # --- SQL templates (database-specific but ordered to catch common asks) ---
    if _ER_RE.search(p):
        from db.schema_discovery import discover_schema
        from viz.mermaid_builder import build_er_diagram

        conn = create_readonly_connection(settings.db_path)
        try:
            schema = discover_schema(conn)
        finally:
            conn.close()
        return {
            "type": "final",
            "answer": "Here is the entity-relationship diagram for this database.",
            "sql": None,
            "chart": None,
            "diagram": {"type": "er", "mermaid": build_er_diagram(schema)},
            "mode": "offline",
        }

    if _TREND_RE.search(p) and _REVENUE_RE.search(p):
        sql = f"SELECT substr(order_date,1,7) AS month, SUM(oi.quantity*oi.unit_price) AS revenue FROM orders o JOIN order_items oi ON o.order_id=oi.order_id WHERE o.status='completed' GROUP BY month ORDER BY month LIMIT 12"
        answer = "Monthly revenue trend."
        chart = chart_hint or "line"
    elif _TOP_RE.search(p) and _REVENUE_RE.search(p):
        n = _TOP_RE.search(p).group(1)
        sql = f"SELECT p.name AS product, SUM(oi.quantity*oi.unit_price) AS revenue FROM order_items oi JOIN products p ON oi.product_id=p.product_id JOIN orders o ON oi.order_id=o.order_id WHERE o.status='completed' GROUP BY p.name ORDER BY revenue DESC LIMIT {n}"
        answer = f"Top {n} products by revenue."
        chart = chart_hint or "bar"
    elif _REVENUE_RE.search(p) and _CATEGORY_RE.search(p):
        sql = f"SELECT p.category, SUM(oi.quantity*oi.unit_price) AS revenue FROM order_items oi JOIN products p ON oi.product_id=p.product_id JOIN orders o ON oi.order_id=o.order_id WHERE o.status='completed' GROUP BY p.category ORDER BY revenue DESC"
        answer = "Revenue by product category."
        chart = chart_hint or "bar"
    elif _REVENUE_RE.search(p) and _CUSTOMER_RE.search(p) and _TOP_RE.search(p):
        n = _TOP_RE.search(p).group(1)
        sql = f"SELECT c.name AS customer, SUM(oi.quantity*oi.unit_price) AS spent FROM orders o JOIN order_items oi ON o.order_id=oi.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE o.status='completed' GROUP BY c.name ORDER BY spent DESC LIMIT {n}"
        answer = f"Top {n} customers by spend."
        chart = chart_hint or "bar"
    elif _CITY_RE.search(p) and _REVENUE_RE.search(p):
        sql = f"SELECT c.city, SUM(oi.quantity*oi.unit_price) AS revenue FROM orders o JOIN order_items oi ON o.order_id=oi.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE o.status='completed' GROUP BY c.city ORDER BY revenue DESC"
        answer = "Revenue by customer city."
        chart = chart_hint or "pie"
    elif _STOCK_RE.search(p):
        sql = "SELECT p.name AS product, p.stock AS stock_level FROM products p ORDER BY p.stock ASC LIMIT 10"
        answer = "Products with lowest stock."
        chart = chart_hint or "bar"
    elif _TOP_RE.search(p) and _PRODUCT_RE.search(p):
        n = _TOP_RE.search(p).group(1)
        sql = f"SELECT p.name AS product, COUNT(oi.order_item_id) AS times_ordered FROM order_items oi JOIN products p ON oi.product_id=p.product_id GROUP BY p.name ORDER BY times_ordered DESC LIMIT {n}"
        answer = f"Top {n} most-ordered products."
        chart = chart_hint or "bar"
    elif _TREND_RE.search(p) or re.search(r"by\s+month|monthly|per\s+month", p):
        sql = f"SELECT substr(o.order_date,1,7) AS month, COUNT(DISTINCT o.order_id) AS orders FROM orders o WHERE o.status='completed' GROUP BY month ORDER BY month LIMIT 12"
        answer = "Monthly order counts."
        chart = chart_hint or "line"
    else:
        # Default: show a small overview.
        sql = f"SELECT COUNT(*) AS order_count, COUNT(DISTINCT customer_id) AS customers FROM orders"
        answer = "Here is a quick overview of your orders table."
        chart = "kpi"

    try:
        result = _run(settings, sql)
    except Exception as exc:  # noqa: BLE001
        return {
            "type": "final",
            "answer": f"I couldn't answer that without a working LLM key. Please add an API key or try a data question.",
            "sql": sql,
            "chart": None,
            "diagram": None,
            "mode": "offline",
            "error": str(exc),
        }

    from viz.recommender import build_chart_spec

    columns, rows = result["columns"], result["rows"]
    chart_spec = None
    if chart and rows:
        chart_spec = build_chart_spec(columns, rows, chart_type=chart)
        chart_spec["title"] = answer
    summary = _summarize_result(result)
    return {
        "type": "final",
        "answer": f"{answer}\n\n{summary}",
        "sql": result["sql"],
        "chart": chart_spec,
        "diagram": diagram,
        "mode": "offline",
    }