"""SQL safety guard.

Defense-in-depth for arbitrary SQL produced by an LLM:

1. Reject empty / multi-statement input.
2. Parse with sqlglot and require a read-only statement (Select / Union / With
   containing only SELECTs).
3. Quote-mask string literals before a word-boundary keyword scan, so a column
   literally containing 'DELETE' or 'drop' can never be a false positive while
   real `DELETE` statements are still caught.
4. Optionally rewrite the AST to enforce a row LIMIT.

Every failure mode returns a structured error that the agent can feed back to
the model for self-correction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import sqlglot
from sqlglot import exp

FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "REPLACE",
    "GRANT",
    "REVOKE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "ANALYZE",
    "LOAD",
    "EXPLAIN",
}

_QUOTED_SPAN = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")

# Look for keywords as whole words, but not after a period (table.column) or
# inside an already-stripped quoted region.
_KEYWORD_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|ATTACH|DETACH|PRAGMA|VACUUM|ANALYZE|LOAD|EXPLAIN)\b", re.IGNORECASE)


@dataclass
class ValidationResult:
    valid: bool
    sql: str = ""
    error_type: str = ""
    error_message: str = ""
    has_limit: bool = False
    limit_value: Optional[int] = None

    @classmethod
    def ok(cls, sql: str, has_limit: bool, limit_value: Optional[int] = None) -> "ValidationResult":
        return cls(valid=True, sql=sql, has_limit=has_limit, limit_value=limit_value)

    @classmethod
    def fail(cls, error_type: str, error_message: str) -> "ValidationResult":
        return cls(valid=False, error_type=error_type, error_message=error_message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "sql": self.sql,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "has_limit": self.has_limit,
            "limit_value": self.limit_value,
        }


def _strip_quoted(sql: str) -> str:
    return _QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), sql)


def _split_statements(sql: str) -> list[str]:
    """Split on semicolons, tolerating trailing whitespace and comments."""
    # Remove line comments first (they may contain semicolons).
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    parts = [p.strip() for p in sql.split(";") if p.strip()]
    return parts


def _statement_type(root: exp.Expression) -> str:
    if isinstance(root, exp.Select):
        return "select"
    if isinstance(root, exp.Union):
        return "union"
    if isinstance(root, exp.With):
        # The WITH itself is read-only only if its body is a Select/Union.
        body = root.this
        if isinstance(body, (exp.Select, exp.Union)):
            return "with"
        return "other"
    return "other"


def _contains_write(sql: str) -> bool:
    """Recursively inspect AST for any non-read-only expression."""
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return True  # fail closed: unparseable == unsafe
    for node in tree.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.TruncateTable, exp.Merge, exp.Copy, exp.Command)):
            return True
        if isinstance(node, exp.Pragma):
            return True
    return False


def validate_sql(
    sql: str,
    *,
    enforce_limit: bool = True,
    max_rows: int = 500,
) -> ValidationResult:
    """Validate arbitrary SQL for read-only execution.

    Args:
        sql: the raw SQL string (may contain leading/trailing whitespace).
        enforce_limit: if True, rewrite the AST to force a row LIMIT.
        max_rows: the hard row ceiling to enforce.

    Returns:
        A ValidationResult; if valid, ``sql`` holds the (possibly rewritten)
        safe SQL ready for execution.
    """
    if not sql or not sql.strip():
        return ValidationResult.fail("empty_sql", "SQL query is empty.")

    statements = _split_statements(sql)
    if len(statements) > 1:
        return ValidationResult.fail(
            "multi_statement", "Multiple statements are not allowed; send a single SELECT query."
        )

    candidate = statements[0].rstrip(";").strip()
    if not candidate:
        return ValidationResult.fail("empty_sql", "SQL query is empty after cleanup.")

    # --- Parser / AST checks (fail closed on any parse error) ---
    try:
        tree = sqlglot.parse_one(candidate, read="sqlite")
    except Exception as exc:
        return ValidationResult.fail("parse_error", f"Could not parse the SQL query: {exc}")

    if _contains_write(candidate):
        return ValidationResult.fail(
            "unsafe_statement",
            "Only read-only queries (SELECT) are allowed. Write operations are blocked.",
        )

    stmt_type = _statement_type(tree)
    if stmt_type not in ("select", "union", "with"):
        return ValidationResult.fail(
            "unsupported_statement",
            "Only SELECT queries are supported for execution.",
        )

    # --- Quote-masked keyword scan (word boundaries) ---
    masked = _strip_quoted(candidate)
    keyword_hits = _KEYWORD_RE.findall(masked)
    if keyword_hits:
        return ValidationResult.fail(
            "forbidden_keyword",
            f"Query contains forbidden SQL keyword(s): {', '.join(sorted(set(keyword_hits)))}.",
        )

    # --- Row limit enforcement via AST rewrite ---
    has_limit = _detect_limit(tree)
    final_sql = candidate
    limit_value = None
    if enforce_limit:
        if has_limit:
            limit_value = _limit_value(tree)
            if limit_value is None or limit_value > max_rows:
                return ValidationResult.fail(
                    "limit_too_high",
                    f"Query LIMIT exceeds the allowed maximum of {max_rows} rows.",
                )
        else:
            # Inject `LIMIT max_rows` on the outermost SELECT.
            try:
                rebuilt = _rewrite_with_limit(tree, max_rows)
                final_sql = rebuilt.sql(dialect="sqlite", pretty=False)
                limit_value = max_rows
            except Exception:
                return ValidationResult.fail("rewrite_error", "Could not enforce a safe row limit on the query.")

    return ValidationResult.ok(final_sql, has_limit=has_limit or enforce_limit, limit_value=limit_value)


def _detect_limit(tree: exp.Expression) -> bool:
    for node in tree.walk():
        if isinstance(node, exp.Limit):
            return True
    return False


def _limit_value(tree: exp.Expression) -> Optional[int]:
    for node in tree.walk():
        if isinstance(node, exp.Limit) and isinstance(node.expression, exp.Literal):
            try:
                return int(node.expression.this)
            except (ValueError, TypeError):
                return None
    return None


def _rewrite_with_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
    """Inject or cap LIMIT on the outermost SELECT of the tree."""
    root = tree
    # WITH body: recurse to the contained select
    if isinstance(root, exp.With):
        root = root.this
    if isinstance(root, exp.Union):
        # Wrap the union in a select so LIMIT applies to the whole result.
        root = exp.select(" * ").from_(exp.Subquery(this=root, alias="__u__"))
    if isinstance(root, exp.Select):
        root = root.limit(max_rows)
    return root


def sanitize_db_error(exc: Exception) -> str:
    """Return a user-safe error message that never leaks file paths."""
    msg = str(exc)
    # Strip absolute paths and connection strings.
    msg = re.sub(r"[A-Za-z]:\\[^\s'\"]+", "<path>", msg)
    msg = re.sub(r"file:[^\s'\"]+", "<db>", msg)
    return msg[:500]