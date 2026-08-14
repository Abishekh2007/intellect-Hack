"""generate_chart tool — create data visualizations.

The server receives result data from execute_query and builds a deterministic
ChartSpec (chart type is chosen by code rules, not LLM whim).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolDefinition
from viz.recommender import build_chart_spec

CHART_TYPES = {"bar", "line", "pie", "scatter", "area", "kpi"}


class GenerateChartInput(BaseModel):
    data: list[dict[str, Any]] = Field(description="Array of row objects: [{column: value}]")
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


def _generate_chart_handler(args: GenerateChartInput, context: dict[str, Any]) -> dict[str, Any]:
    columns, rows = _rows_to_table(args.data)
    spec = build_chart_spec(columns, rows, chart_type=args.chart_type)
    spec["title"] = args.title
    return {"chart": spec}


generate_chart_tool = ToolDefinition(
    name="generate_chart",
    description=(
        "Create a data visualization (bar, line, pie, scatter, area, or KPI) "
        "from a set of result rows. Pass the rows as a list of objects. The "
        "best chart type is chosen automatically based on the data shape."
    ),
    input_model=GenerateChartInput,
    handler=_generate_chart_handler,
)