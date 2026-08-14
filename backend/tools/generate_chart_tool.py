"""generate_chart tool — create data visualizations.

The server receives result data from execute_query and builds a deterministic
ChartSpec (chart type is chosen by code rules, not LLM whim).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from store import result_store
from tools.registry import ToolDefinition, ToolError
from viz.recommender import build_chart_spec

CHART_TYPES = {"bar", "line", "pie", "scatter", "area", "kpi"}


class GenerateChartInput(BaseModel):
    result_id: str | None = Field(
        default=None,
        description=(
            "The result_id returned by execute_query. Preferred — charts the "
            "full result rather than the preview rows."
        ),
    )
    data: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Array of row objects: [{column: value}]. Only for data that did "
            "not come from execute_query; otherwise pass result_id instead."
        ),
    )
    chart_type: str | None = Field(
        default=None,
        description="Optional hint: bar, line, pie, scatter, area, or kpi. Leave null for automatic.",
    )
    title: str = Field(default="", description="Optional chart title.")


def _rows_to_table(data: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    if not data:
        return [], []
    columns = list(data[0].keys())
    rows = [[row.get(c) for c in columns] for row in data]
    return columns, rows


def _resolve_rows(result_id: str | None, data: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Prefer the stored result; fall back to inline rows.

    A stale result_id is recoverable — the model can re-run the query — so it
    raises rather than silently charting whatever was inlined alongside it.
    """
    if result_id:
        rows = result_store.rows_as_dicts(result_id)
        if rows is not None:
            return rows
        if not data:
            raise ToolError(
                "unknown_result_id",
                f"No stored result for result_id={result_id!r}. It may have expired — "
                "re-run execute_query and use the new result_id.",
            )
    return data or []


def _generate_chart_handler(args: GenerateChartInput, context: dict[str, Any]) -> dict[str, Any]:
    columns, rows = _rows_to_table(_resolve_rows(args.result_id, args.data))
    # The question and the title both carry wording the data shape can't ("what
    # share of revenue...", "category breakdown"), so both feed the recommender.
    intent = " ".join(filter(None, [context.get("user_message", ""), args.title]))
    spec = build_chart_spec(columns, rows, chart_type=args.chart_type, intent=intent)
    spec["title"] = args.title
    return {"chart": spec}


generate_chart_tool = ToolDefinition(
    name="generate_chart",
    description=(
        "Create a data visualization (bar, line, pie, scatter, area, or KPI). "
        "Pass the result_id from execute_query — the full result is read "
        "server-side, so do not copy rows into this call. The best chart type "
        "is chosen automatically from the data shape and the question, so "
        "leave chart_type null unless the user named a specific type."
    ),
    input_model=GenerateChartInput,
    handler=_generate_chart_handler,
)