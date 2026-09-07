"""generate_flowchart tool — create ER diagrams, process flows, decision trees."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from db.connections import demo_connection
from db.schema_discovery import discover_schema_for
from tools.registry import ToolDefinition, ToolError
from viz.mermaid_builder import build_decision_tree, build_er_diagram, build_flowchart


class GenerateFlowchartInput(BaseModel):
    diagram_type: str = Field(
        description="'er', 'process', or 'decision'.",
    )
    steps: list[str] | None = Field(
        default=None,
        description="Ordered process steps, required for 'process' diagrams.",
    )
    nodes: list[dict[str, Any]] | None = Field(
        default=None,
        description="Decision-tree nodes [{label, type, parent, edge}], required for 'decision'.",
    )
    title: str = Field(default="", description="Optional diagram title.")


def _generate_flowchart_handler(args: GenerateFlowchartInput, context: dict[str, Any]) -> dict[str, Any]:
    diagram_type = (args.diagram_type or "er").lower()

    if diagram_type == "er":
        connection = context.get("connection") or demo_connection()
        mermaid = build_er_diagram(discover_schema_for(connection))
        return {"diagram_type": "er", "mermaid": mermaid}

    # Failures are raised, not returned. A returned {"error": ...} came back
    # wrapped as a *successful* ToolResult, so the agent loop saw success, found
    # no "mermaid" key, emitted nothing, and the model was never told what went
    # wrong — the request simply vanished. ToolError reaches the model instead.
    if diagram_type == "process":
        steps = args.steps or []
        if not steps:
            raise ToolError(
                "missing_steps",
                "Process diagrams require a non-empty `steps` list. Pass the "
                "ordered step labels and call generate_flowchart again.",
            )
        mermaid = build_flowchart(steps, title=args.title)
        return {"diagram_type": "process", "mermaid": mermaid, "steps": steps}

    if diagram_type == "decision":
        nodes = args.nodes or []
        if not nodes:
            raise ToolError(
                "missing_nodes",
                "Decision diagrams require a non-empty `nodes` list of "
                "{label, type, parent, edge} objects.",
            )
        mermaid = build_decision_tree(nodes)
        return {"diagram_type": "decision", "mermaid": mermaid}

    raise ToolError(
        "unknown_diagram_type",
        f"Unknown diagram type {diagram_type!r}. Use 'er', 'process' or 'decision'.",
    )


generate_flowchart_tool = ToolDefinition(
    name="generate_flowchart",
    description=(
        "Create a diagram rendered with Mermaid. Supports: 'er' (entity-relationship "
        "diagram from the database foreign keys), 'process' (flowchart from ordered "
        "steps), and 'decision' (decision tree from labeled nodes)."
    ),
    input_model=GenerateFlowchartInput,
    handler=_generate_flowchart_handler,
)