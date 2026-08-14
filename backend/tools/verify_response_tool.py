"""verify_response tool — self-audit that requested artifacts were delivered.

Computes what the user asked for vs. what the agent actually produced
(chart? diagram? explanation?) and returns a completion ratio. Partial results
are disclosed honestly instead of being glossed over.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolDefinition


class VerifyResponseInput(BaseModel):
    user_request: str = Field(description="The original user question.")
    produced: dict[str, bool] = Field(
        default_factory=dict,
        description="Which artifacts were produced, e.g. {\"chart\": true, \"diagram\": false, \"explanation\": true}.",
    )


_CHART_HINTS = re.compile(r"chart|graph|plot|visuali[sz]e|pie|bar|line|scatter", re.IGNORECASE)
_DIAGRAM_HINTS = re.compile(r"diagram|er\b|entity|flowchart|flow chart|process|decision tree", re.IGNORECASE)
_EXPLAIN_HINTS = re.compile(r"explain|why|insight|summarize|interpret|meaning|trend|compare", re.IGNORECASE)


def _verify_response_handler(args: VerifyResponseInput, context: dict[str, Any]) -> dict[str, Any]:
    request = args.user_request or ""
    produced = args.produced or {}

    wanted = {
        "chart": bool(_CHART_HINTS.search(request)),
        "diagram": bool(_DIAGRAM_HINTS.search(request)),
        "explanation": bool(_EXPLAIN_HINTS.search(request)),
    }

    delivered = []
    missing = []
    for artifact, requested in wanted.items():
        if not requested:
            continue
        if produced.get(artifact):
            delivered.append(artifact)
        else:
            missing.append(artifact)

    total_requested = len(delivered) + len(missing)
    completion_ratio = round(len(delivered) / total_requested, 2) if total_requested else 1.0
    status = "complete" if not missing else ("partial" if delivered else "failed")

    return {
        "status": status,
        "requested_artifacts": [k for k, v in wanted.items() if v],
        "delivered_artifacts": delivered,
        "missing_artifacts": missing,
        "completion_ratio": completion_ratio,
    }


verify_response_tool = ToolDefinition(
    name="verify_response",
    description=(
        "Check whether the final answer delivered everything the user asked for "
        "(chart, diagram, explanation). Call this before finishing a turn so "
        "missing artifacts can be generated."
    ),
    input_model=VerifyResponseInput,
    handler=_verify_response_handler,
)