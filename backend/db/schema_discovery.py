"""Schema discovery.

Returns a JSON-safe representation of the database: tables, columns,
types, primary keys and foreign keys. Used both to inject context into
the LLM prompt and to power ER-diagram generation.
"""

import re
import sqlite3
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

        # Cheap on SQLite, and best-effort: a table that cannot be counted
        # (a corrupt page, a lock) simply reports no count rather than
        # taking the whole schema request down with it.
        try:
            row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        except sqlite3.Error:
            row_count = None

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
                "row_count": row_count,
            }
        )

    return {"tables": tables}


def schema_to_prompt(schema: dict[str, Any]) -> str:
    """Render the schema as compact text for LLM prompting.

    Row counts are included when discovery could measure them: knowing a table
    holds 7 rows rather than 7 million is the difference between "SELECT *" and
    "GROUP BY", and without it the model cannot tell whether a result it just
    received is the whole table or the top of a much larger one.
    """
    lines: list[str] = []
    for table in schema["tables"]:
        col_str = ", ".join(
            f"{c['name']}:{c['type']}{' PK' if c['pk'] else ''}{' NULL' if c['nullable'] else ''}"
            for c in table["columns"]
        )
        count = table.get("row_count")
        suffix = f"  -- {count:,} rows" if isinstance(count, int) else ""
        lines.append(f"TABLE {table['name']} ( {col_str} ){suffix}")
        for fk in table["foreign_keys"]:
            lines.append(
                f"  FK {table['name']}.{fk['column']} -> {fk['references_table']}.{fk['references_column']}"
            )
    return "\n".join(lines)


_MERMAID_IDENT = re.compile(r"[^A-Za-z0-9_]")


def _er_ident(name: str) -> str:
    """A Mermaid-safe identifier. Mermaid accepts no spaces or punctuation."""
    return _MERMAID_IDENT.sub("_", str(name)) or "unnamed"


def relationships_as_mermaid_er(schema: dict[str, Any]) -> str:
    """Build a Mermaid erDiagram from the discovered foreign keys.

    Three things this gets right that the previous version did not, each of
    which stopped the diagram rendering or made it say the wrong thing:

    * Entity blocks put every attribute on its own line, ``type name`` in that
      order. Mermaid's grammar is line-based and type-first; a single-line
      ``{ order_id INTEGER }`` is a parse error as soon as a table has two
      primary-key columns.
    * The relationship line ends after the label. The old f-string escaped a
      closing brace onto the end of it — ``a ||--o{ b : "references" }`` — and
      that trailing brace failed to parse, so the ER diagram never drew.
    * The crow's foot points at the child. A foreign key on ``orders`` that
      references ``customers`` means many orders per customer, so the parent
      is on the ``||`` side. It was emitted the other way round, telling the
      reader every customer belongs to one order.
    """
    lines = ["erDiagram"]

    seen: set[tuple[str, str, str]] = set()
    for table in schema["tables"]:
        child = _er_ident(table["name"])
        for fk in table.get("foreign_keys") or []:
            parent = _er_ident(fk["references_table"])
            key = (parent, child, fk["column"])
            if key in seen:
                continue
            seen.add(key)
            label = _er_ident(fk["column"])
            lines.append(f'    {parent} ||--o{{ {child} : "{label}"')

    for table in schema["tables"]:
        columns = table.get("columns") or []
        if not columns:
            continue
        # Show keys first, then the rest, so wide tables stay readable.
        shown = [c for c in columns if c.get("pk")][:4]
        fk_cols = {fk["column"] for fk in (table.get("foreign_keys") or [])}
        shown += [c for c in columns if not c.get("pk") and c["name"] in fk_cols][:4]
        if not shown:
            shown = columns[:4]
        lines.append(f'    {_er_ident(table["name"])} {{')
        for c in shown:
            marker = " PK" if c.get("pk") else (" FK" if c["name"] in fk_cols else "")
            lines.append(f'        {_er_ident(c["type"]) or "text"} {_er_ident(c["name"])}{marker}')
        lines.append("    }")

    return "\n".join(lines)


def get_schema_json(settings=None) -> dict[str, Any]:
    from config import get_settings

    settings = settings or get_settings()
    conn = create_readonly_connection(settings.db_path)
    try:
        return discover_schema(conn)
    finally:
        conn.close()


def discover_schema_for(connection) -> dict[str, Any]:
    """Discover the schema of any supported engine.

    Returns the same JSON shape for every engine, so the ER-diagram builder
    and the prompt renderer stay engine-agnostic.
    """
    from db.connections import POSTGRES_KIND

    if connection.kind == POSTGRES_KIND:
        from db import postgres

        return postgres.discover_schema(connection.target)

    conn = create_readonly_connection(connection.db_path)
    try:
        return discover_schema(conn)
    finally:
        conn.close()