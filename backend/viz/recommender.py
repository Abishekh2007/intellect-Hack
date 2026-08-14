"""Deterministic chart recommendation.

Profiles result columns (numeric vs temporal vs categorical, cardinality) and
picks the *most appropriate* chart type by code rules — the same question
always yields the same chart, and we never ask the LLM to choose a chart type
that will look wrong.

Selection rules, in priority order:

1. explicit hint (user or model asked for a specific type) -> honour it
2. single column                                          -> kpi
3. temporal x-axis                                        -> line (bar if <=2 points)
4. share-of-total intent + partition-shaped data          -> pie
5. two or more numeric columns, no categorical x          -> scatter
6. everything else                                        -> bar

Rule 4 needs the *question*, not just the data: "revenue by category" and
"top 5 products by revenue" are the same shape, but only the first describes
a whole being divided up. Shape alone cannot tell them apart, so pie is gated
on an intent signal and falls back to bar when there isn't one.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

DATE_LIKE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
YEAR_LIKE = re.compile(r"^\d{4}$")
MONTH_LIKE = re.compile(r"^\d{4}[-/]\d{1,2}$")
PRICE_LIKE = re.compile(r"price|revenue|amount|sales|cost|profit|total|sum|count|avg|qty|quantity|stock", re.IGNORECASE)

# Words that mean "how does the whole divide up", which is what a pie answers.
SHARE_INTENT = re.compile(
    r"\bshare\b|\bshares\b|proportion|percentage|percent|\bpct\b|distribution|"
    r"breakdown|break down|composition|split|make ?up|ratio|\bmix\b|out of total|"
    r"of total|contribution",
    re.IGNORECASE,
)

# A pie stops being readable past a handful of slices.
MAX_PIE_SLICES = 8

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


def _first_date_index(profiles: list[dict[str, Any]]) -> int:
    for i, p in enumerate(profiles):
        if p["date_ratio"] > 0.6:
            return i
    return -1


def _numeric_indices(profiles: list[dict[str, Any]]) -> list[int]:
    return [i for i, p in enumerate(profiles) if p["numeric_ratio"] > 0.6]


def _first_categorical_index(profiles: list[dict[str, Any]]) -> int:
    """First column that reads as a label rather than a measure."""
    for i, p in enumerate(profiles):
        if p["numeric_ratio"] <= 0.5 and p["date_ratio"] <= 0.6:
            return i
    return -1


def _suits_pie(
    profiles: list[dict[str, Any]],
    rows: list[list[Any]],
    cat_idx: int,
    num_idx: int,
) -> bool:
    """A pie needs one label column, one non-negative measure, few slices."""
    if cat_idx < 0 or num_idx < 0:
        return False
    slices = profiles[cat_idx]["cardinality"]
    if not 2 <= slices <= MAX_PIE_SLICES:
        return False
    # Slices must not repeat a category, or the wedges double up.
    if slices != len(rows):
        return False
    # Negative values have no meaningful area on a pie.
    for row in rows:
        if num_idx >= len(row):
            return False
        value = row[num_idx]
        if not _is_numeric(value):
            return False
        if float(str(value).replace(",", "")) < 0:
            return False
    return True


def recommend_chart(
    columns: list[str],
    rows: list[list[Any]],
    hint: str | None = None,
    intent: str = "",
) -> str:
    """Pick the most appropriate chart type by deterministic rules.

    Args:
        columns: result column names.
        rows: result rows (list of lists).
        hint: optional explicitly-requested chart type (validated against
            CHART_TYPES); short-circuits every rule below.
        intent: the user's question, used only to detect share-of-total
            phrasing that the data shape cannot express. Never used to pick a
            type the data doesn't support.

    Returns one of: bar, line, pie, scatter, area, kpi.
    """
    if not columns or not rows:
        return "kpi"
    if hint and hint in CHART_TYPES:
        return hint
    if len(columns) == 1:
        return "kpi"

    profiles = profile_columns(columns, rows)
    date_idx = _first_date_index(profiles)
    numeric_idx = _numeric_indices(profiles)
    cat_idx = _first_categorical_index(profiles)

    # Temporal x-axis -> line (a two-point "trend" reads better as bars).
    if date_idx >= 0 and numeric_idx:
        return "bar" if profiles[date_idx]["cardinality"] <= 2 else "line"

    # Share-of-total question over partition-shaped data -> pie.
    if (
        numeric_idx
        and SHARE_INTENT.search(intent or "")
        and _suits_pie(profiles, rows, cat_idx, numeric_idx[0])
    ):
        return "pie"

    # Two measures and nothing to put on a categorical axis -> scatter.
    if len(numeric_idx) >= 2 and cat_idx < 0 and date_idx < 0:
        return "scatter"

    return "bar"


def build_chart_spec(
    columns: list[str],
    rows: list[list[Any]],
    chart_type: str | None = None,
    intent: str = "",
) -> dict[str, Any]:
    """Build a ChartSpec JSON the frontend can render directly."""
    if not columns or not rows:
        return {"type": "kpi", "columns": columns, "rows": rows}

    profiles = profile_columns(columns, rows)
    ctype = recommend_chart(columns, rows, hint=chart_type, intent=intent)

    numeric_idx = _numeric_indices(profiles)

    if ctype == "scatter" and len(numeric_idx) >= 2:
        # Both axes are measures; keep them in column order.
        x_key = profiles[numeric_idx[0]]["name"]
        y_key = profiles[numeric_idx[1]]["name"]
    else:
        x_key = columns[0]
        y_key = columns[-1]
        date_idx = _first_date_index(profiles)
        cat_idx = _first_categorical_index(profiles)
        if date_idx >= 0:
            x_key = profiles[date_idx]["name"]
        elif cat_idx >= 0:
            x_key = profiles[cat_idx]["name"]
        for i in numeric_idx:
            if profiles[i]["name"] != x_key:
                y_key = profiles[i]["name"]
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