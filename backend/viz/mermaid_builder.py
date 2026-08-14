"""Mermaid diagram builders.

Generate ER diagrams from real foreign keys, process flow diagrams from
ordered steps, and decision trees from labeled data. All output is generated
deterministically — never by the LLM — so rendering never breaks the chat.
"""

from __future__ import annotations

from typing import Any

from db.schema_discovery import relationships_as_mermaid_er


def build_er_diagram(schema: dict[str, Any]) -> str:
    return relationships_as_mermaid_er(schema)


def build_flowchart(steps: list[str], title: str = "Process Flow") -> str:
    lines = [f"flowchart TD", f'    A["{_escape(title)}"]']
    for i, step in enumerate(steps):
        lines.append(f'    S{i}["{_escape(str(step))}"]')
        if i == 0:
            lines.append("    A --> S0")
        else:
            lines.append(f"    S{i-1} --> S{i}")
    return "\n".join(lines)


def build_decision_tree(nodes: list[dict[str, Any]]) -> str:
    """Build a Mermaid decision tree from {node, label, decision, children} data."""
    lines = ["flowchart TD"]
    lines.append('    N0{"Start"}')
    for i, node in enumerate(nodes):
        nid = f"N{i+1}"
        if node.get("type") == "decision":
            lines.append(f'    {nid}{{{{"{_escape(node.get("label", ""))}"}}}}')
        else:
            lines.append(f'    {nid}["{_escape(node.get("label", ""))}"]')
        parent = node.get("parent", 0)
        pnid = f"N{parent}" if parent else "N0"
        lines.append(f"    {pnid} -->|{_escape(node.get('edge', ''))}| {nid}")
    return "\n".join(lines)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace('"', "'")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("[", "(")
        .replace("]", ")")
    )