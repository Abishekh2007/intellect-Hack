"""Deterministic chart recommendation.

Profiles result columns (numeric vs temporal vs categorical, cardinality) and
picks the *most appropriate* chart type by code rules — the same question
always yields the same chart, and we never ask the LLM to choose a chart type
that will look wrong.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

DATE_LIKE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
YEAR_LIKE = re.compile(r"^\d{4}$")
MONTH_LIKE = re.compile(r"^\d{4}[-/]\d{1,2}$")
PRICE_LIKE = re.compile(r"price|revenue|amount|sales|cost|profit|total|sum|count|avg|qty|quantity|stock", re.IGNORECASE)

CHART_TYPES = {"bar", "line", "pie", "scatter", "area", "kpi"}


def _is_numeric(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
            return True
        except ValueError:
            return False
    return False


def _is_date(value: Any) -> bool:
    if isinstance(value, str):
        v = value.strip()
        if DATE_LIKE.match(v) or MONTH_LIKE.match(v) or YEAR_LIKE.match(v):
            return True
        try:
            datetime.fromisoformat(v)
            return True
        except ValueError:
            return False
    return False


def profile_columns(columns: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    """Return per-column metadata: sample type, cardinality, date-likeness."""
    if not columns:
        return []
    n = len(columns)
    profiles = []
    for idx in range(n):
        values = [row[idx] for row in rows if idx < len(row)]
        non_null = [v for v in values if v is not None and str(v).strip() != ""]
        numeric = sum(1 for v in non_null if _is_numeric(v))
        date = sum(1 for v in non_null if _is_date(v))
        profiles.append(
            {
                "name": columns[idx],
                "cardinality": len(set(str(v) for v in non_null)),
                "total": len(non_null),
                "numeric_ratio": numeric / len(non_null) if non_null else 0.0,
                "date_ratio": date / len(non_null) if non_null else 0.0,
            }
        )
    return profiles


def recommend_chart(columns: list[str], rows: list[list[Any]], hint: str | None = None) -> str:
    """Pick the most appropriate chart type by deterministic rules.

    Args:
        columns: result column names.
        rows: result rows (list of lists).
        hint: optional user-requested chart type (validated against CHART_TYPES).

    Returns one of: bar, line, pie, scatter, area, kpi.
    """
    if not columns or not rows:
        return "kpi"
    if hint and hint in CHART_TYPES:
        return hint

    profiles = profile_columns(columns, rows)
    if len(columns) == 1:
        return "kpi"

    # Identify the best x (first non-numeric, or first date column).
    x_idx = 0
    date_idx = -1
    numeric_idx = -1
    for p in profiles:
        if p["date_ratio"] > 0.6:
            date_idx = profiles.index(p)
            break
    for p in profiles:
        if p["numeric_ratio"] > 0.6 and numeric_idx == -1:
            numeric_idx = profiles.index(p)
        if p["numeric_ratio"] <= 0.5 and date_idx == -1:
            x_idx = profiles.index(p)
            break
    if date_idx == -1 and numeric_idx >= 0 and x_idx == numeric_idx:
        x_idx = 0

    # Temporal x-axis → line chart.
    if date_idx >= 0:
        # Still bar if few distinct points and user context suggests comparison
        cardinality = profiles[date_idx]["cardinality"]
        if cardinality <= 2:
            return "bar"
        return "line"

    n_distinct = profiles[x_idx]["cardinality"] if profiles else 1
    if n_distinct <= 8 and numeric_idx >= 0:
        # Categorical + proportional → pie; otherwise bar.
        # Pie is best for share-of-total; bar for ranking.
        return "bar"
    if n_distinct > 8 and numeric_idx >= 0:
        if sum(p["numeric_ratio"] > 0.6 for p in profiles) >= 2:
            return "scatter"
        return "bar"
    return "bar"


def build_chart_spec(columns: list[str], rows: list[list[Any]], chart_type: str | None = None) -> dict[str, Any]:
    """Build a ChartSpec JSON the frontend can render directly."""
    if not columns or not rows:
        return {"type": "kpi", "columns": columns, "rows": rows}

    profiles = profile_columns(columns, rows)
    ctype = recommend_chart(columns, rows, hint=chart_type)

    x_key = columns[0]
    y_key = columns[-1]
    for p in profiles:
        if p["date_ratio"] > 0.6:
            x_key = p["name"]
            break
    for p in profiles:
        if p["numeric_ratio"] > 0.6 and p["name"] != x_key:
            y_key = p["name"]
            break

    spec: dict[str, Any] = {
        "type": ctype,
        "columns": columns,
        "x_key": x_key,
        "y_key": y_key,
        "rows": rows,
        "recommended": True,
    }
    return spec