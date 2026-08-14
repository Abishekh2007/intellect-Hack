"""explain_data tool — generate grounded insights from result data.

Computes real descriptive statistics server-side (never hallucinated) and,
when an LLM is available, produces a natural-language summary. The model is
given *only* the computed statistics, never the raw rows, so the prose can
only describe numbers that were actually measured. Without a provider — or if
one fails — the deterministic template still produces a correct answer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from store import result_store
from tools.registry import ToolDefinition, ToolError


class ExplainDataInput(BaseModel):
    result_id: str | None = Field(
        default=None,
        description=(
            "The result_id returned by execute_query. Preferred — explains the "
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
    context: str = Field(default="", description="Optional user question being answered.")


def _aggregate(data: list[dict[str, Any]]) -> dict[str, Any]:
    if not data:
        return {"count": 0}
    columns = list(data[0].keys())
    stats: dict[str, Any] = {"count": len(data), "columns": columns}
    # Per-column statistics describe each column in isolation, which loses the
    # pairing between a label and its measure — without this the model can
    # report the top revenue figure but not which product earned it.
    stats["leading_rows"] = data[:5]
    if len(data) > 5:
        stats["trailing_rows"] = data[-3:]
    for col in columns:
        if col in ("leading_rows", "trailing_rows"):
            continue
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


_INSIGHT_SYSTEM = """You are a data analyst writing a short insight for a business user.

You are given ONLY pre-computed statistics from a query result, plus a few
verbatim rows from the top and bottom of it. Every number and name in your
answer must come from that material — do not estimate, extrapolate, or invent
figures. Use the verbatim rows to say which item a figure belongs to; use the
statistics for totals, averages and ranges across the whole result.

Write 2-4 sentences of plain prose. Lead with the most useful finding, name the
figures that support it, and note anything that looks like an outlier or a
sharp change. No preamble, no bullet points, no markdown headings."""


def _llm_explanation(stats: dict[str, Any], question: str, llm: Any) -> str | None:
    """Ask the model to narrate the computed statistics. None if unavailable."""
    if llm is None:
        return None
    prompt = (
        f"User's question: {question or '(not provided)'}\n\n"
        f"Computed statistics:\n{json.dumps(stats, default=str, indent=2)}"
    )
    try:
        text_parts: list[str] = []
        for event in llm.stream_tool_calls([{"role": "user", "content": prompt}], [], _INSIGHT_SYSTEM):
            if event.get("type") == "text":
                text_parts.append(event["text"])
        explanation = "".join(text_parts).strip()
        return explanation or None
    except Exception as exc:  # noqa: BLE001
        # An insight is a nice-to-have; the deterministic summary still stands.
        logging.warning("explain_data LLM narration failed, using template: %s", exc)
        return None


def _explain_data_handler(args: ExplainDataInput, context: dict[str, Any]) -> dict[str, Any]:
    rows = args.data
    if args.result_id:
        stored = result_store.rows_as_dicts(args.result_id)
        if stored is None and not rows:
            raise ToolError(
                "unknown_result_id",
                f"No stored result for result_id={args.result_id!r}. It may have expired — "
                "re-run execute_query and use the new result_id.",
            )
        if stored is not None:
            rows = stored

    stats = _aggregate(rows or [])
    template = _fallback_explanation(stats, args.context)
    narrated = _llm_explanation(stats, args.context, context.get("llm"))
    return {
        "explanation": narrated or template,
        "statistics": stats,
        "grounded_summary": template,
        "source": "llm" if narrated else "computed",
    }


explain_data_tool = ToolDefinition(
    name="explain_data",
    description=(
        "Generate insights and a natural-language explanation of a query "
        "result. Pass the result_id from execute_query — statistics are "
        "computed server-side over the full result, so do not copy rows into "
        "this call. Use it after execute_query to explain what the data means."
    ),
    input_model=ExplainDataInput,
    handler=_explain_data_handler,
)