"""explain_data tool — generate grounded insights from result data.

Computes real descriptive statistics server-side (never hallucinated) and,
when an LLM is available, produces a natural-language summary. The summary is
built from the same numbers the user sees.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolDefinition
from viz.recommender import _is_numeric


class ExplainDataInput(BaseModel):
    data: list[dict[str, Any]] = Field(description="Array of row objects: [{column: value}]")
    context: str = Field(default="", description="Optional user question being answered.")


def _aggregate(data: list[dict[str, Any]]) -> dict[str, Any]:
    if not data:
        return {"count": 0}
    columns = list(data[0].keys())
    stats: dict[str, Any] = {"count": len(data), "columns": columns}
    for col in columns:
        values = [row.get(col) for row in data]
        numeric = [v for v in values if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.', '', 1).isdigit())]
        if numeric:
            nums = [float(v) for v in numeric]
            stats[col] = {
                "sum": round(sum(nums), 2),
                "avg": round(sum(nums) / len(nums), 2),
                "min": round(min(nums), 2),
                "max": round(max(nums), 2),
            }
        else:
            counts: dict[str, int] = {}
            for v in values:
                key = str(v)
                counts[key] = counts.get(key, 0) + 1
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            stats[col] = {"top_values": [{"value": k, "count": c} for k, c in top]}
    return stats


def _fallback_explanation(stats: dict[str, Any], context: str) -> str:
    if not stats.get("count"):
        return "The query returned no rows, so there is nothing to explain."
    parts = [f"The result contains {stats['count']} rows."]
    for col in stats.get("columns", []):
        detail = stats.get(col)
        if not detail or not isinstance(detail, dict):
            continue
        if "sum" in detail:
            parts.append(
                f"'{col}': total {detail['sum']}, average {detail['avg']}, "
                f"ranging from {detail['min']} to {detail['max']}."
            )
        elif "top_values" in detail:
            top = detail["top_values"]
            top_str = ", ".join(f"{t['value']} ({t['count']}x)" for t in top[:3])
            parts.append(f"'{col}': most common values are {top_str}.")
    text = " ".join(parts)
    if context:
        text += f" This answers: \"{context}\""
    return text


def _explain_data_handler(args: ExplainDataInput, context: dict[str, Any]) -> dict[str, Any]:
    stats = _aggregate(args.data)
    explanation = _fallback_explanation(stats, args.context)
    return {"explanation": explanation, "statistics": stats}


explain_data_tool = ToolDefinition(
    name="explain_data",
    description=(
        "Generate insights and a natural-language explanation from a set of "
        "result rows. Pass the rows as a list of objects. Use this AFTER "
        "execute_query to help the user understand what the data means."
    ),
    input_model=ExplainDataInput,
    handler=_explain_data_handler,
)