"""generate_flowchart tool — create ER diagrams, process flows, decision trees."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from db.engine import create_readonly_connection
from db.schema_discovery import discover_schema
from tools.registry import ToolDefinition
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
        settings = context.get("settings")
        conn = create_readonly_connection(settings.db_path)
        try:
            schema = discover_schema(conn)
        finally:
            conn.close()
        mermaid = build_er_diagram(schema)
        return {"diagram_type": "er", "mermaid": mermaid}

    if diagram_type == "process":
        steps = args.steps or []
        if not steps:
            return {"error": "Process diagrams require a non-empty list of steps."}
        mermaid = build_flowchart(steps, title=args.title)
        return {"diagram_type": "process", "mermaid": mermaid, "steps": steps}

    if diagram_type == "decision":
        nodes = args.nodes or []
        if not nodes:
            return {"error": "Decision diagrams require node definitions."}
        mermaid = build_decision_tree(nodes)
        return {"diagram_type": "decision", "mermaid": mermaid}

    return {"error": f"Unknown diagram type: {diagram_type}. Use 'er', 'process' or 'decision'."}


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