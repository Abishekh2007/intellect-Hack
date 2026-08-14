"""Schema discovery.

Returns a JSON-safe representation of the database: tables, columns,
types, primary keys and foreign keys. Used both to inject context into
the LLM prompt and to power ER-diagram generation.
"""

import sqlite3
import json
from pathlib import Path
from typing import Any

from db.engine import create_readonly_connection


def discover_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    """Discover the full schema of an open SQLite connection.

    Returns:
        {
          "tables": [
            {"name": str, "columns": [{"name","type","nullable","pk"}],
             "primary_keys": [...], "foreign_keys": [...]}
          ]
        }
    """
    tables: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    for row in rows:
        table_name = row["name"]
        cols = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        fks = conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()

        pk_cols = [c["name"] for c in cols if c["pk"]]
        columns = [
            {
                "name": c["name"],
                "type": c["type"],
                "nullable": not bool(c["notnull"]),
                "pk": bool(c["pk"]),
            }
            for c in cols
        ]
        foreign_keys = [
            {
                "column": fk["from"],
                "references_table": fk["table"],
                "references_column": fk["to"],
            }
            for fk in fks
        ]
        tables.append(
            {
                "name": table_name,
                "columns": columns,
                "primary_keys": pk_cols,
                "foreign_keys": foreign_keys,
            }
        )

    return {"tables": tables}


def schema_to_prompt(schema: dict[str, Any]) -> str:
    """Render the schema as compact text for LLM prompting."""
    lines: list[str] = []
    for table in schema["tables"]:
        col_str = ", ".join(
            f"{c['name']}:{c['type']}{' PK' if c['pk'] else ''}{' NULL' if c['nullable'] else ''}"
            for c in table["columns"]
        )
        lines.append(f"TABLE {table['name']} ( {col_str} )")
        for fk in table["foreign_keys"]:
            lines.append(
                f"  FK {table['name']}.{fk['column']} -> {fk['references_table']}.{fk['references_column']}"
            )
    return "\n".join(lines)


def relationships_as_mermaid_er(schema: dict[str, Any]) -> str:
    """Build a Mermaid erDiagram from the discovered foreign keys."""
    lines = ["erDiagram"]
    table_names: set[str] = set()
    for table in schema["tables"]:
        table_names.add(table["name"])
        # Only declare tables that participate in a relationship to keep the
        # diagram clean; standalone tables get declared too.
    for table in schema["tables"]:
        name = table["name"]
        safe = name.replace(" ", "_")
        if not table["columns"]:
            continue
        pk_list = ", ".join(f"{c['name']} {c['type']}" for c in table["columns"] if c["pk"])
        if pk_list:
            lines.append(f'    {safe} {{ {pk_list} }}')
    seen: set[tuple[str, str, str]] = set()
    for table in schema["tables"]:
        for fk in table["foreign_keys"]:
            from_t = table["name"].replace(" ", "_")
            to_t = fk["references_table"].replace(" ", "_")
            key = (from_t, to_t, fk["column"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f'    {from_t} ||--o{{ {to_t} : "references" }}')
    return "\n".join(lines)


def get_schema_json(settings=None) -> dict[str, Any]:
    from config import get_settings

    settings = settings or get_settings()
    conn = create_readonly_connection(settings.db_path)
    try:
        return discover_schema(conn)
    finally:
        conn.close()