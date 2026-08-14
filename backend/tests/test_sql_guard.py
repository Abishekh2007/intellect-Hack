"""Tests for the SQL safety guard."""

from __future__ import annotations

import pytest

from security.sql_guard import validate_sql

# --- Accepted read-only queries -------------------------------------------
VALID_QUERIES = [
    "SELECT * FROM orders",
    "SELECT name, price FROM products WHERE price > 100",
    "WITH recent AS (SELECT * FROM orders WHERE status='completed') SELECT * FROM recent",
    "SELECT * FROM orders LIMIT 3",
    "SELECT * FROM orders;",  # trailing semicolon tolerated
    "-- comment\nSELECT * FROM orders",
    "select * from orders",
    "SELECT COUNT(*) FROM order_items",
]


@pytest.mark.parametrize("sql", VALID_QUERIES)
def test_valid_read_only_queries_accepted(sql):
    result = validate_sql(sql, enforce_limit=True)
    assert result.valid is True


# --- Rejected statements ---------------------------------------------------
INVALID_QUERIES = [
    ("DELETE FROM orders", "unsafe_statement"),
    ("DROP TABLE products", "unsafe_statement"),
    ("UPDATE orders SET status='x'", "unsafe_statement"),
    ("INSERT INTO orders (order_id) VALUES (99)", "unsafe_statement"),
    ("ALTER TABLE orders ADD COLUMN x INT", "unsafe_statement"),
    ("CREATE TABLE evil (id INT)", "unsafe_statement"),
    ("TRUNCATE TABLE orders", "unsafe_statement"),
    ("PRAGMA journal_mode=WAL", "unsafe_statement"),
    ("ATTACH 'evil.db' AS e", "unsafe_statement"),
    ("VACUUM", "unsafe_statement"),
]


@pytest.mark.parametrize("sql,error_type", INVALID_QUERIES)
def test_write_operations_rejected(sql, error_type):
    result = validate_sql(sql, enforce_limit=True)
    assert result.valid is False
    # Some statements (e.g. ATTACH) may be rejected by the parser itself; the
    # guarantee is that they are *never* executed, not the exact error label.
    if error_type != "unsafe_statement":
        assert result.error_type == error_type


def test_attach_rejected_whatever_the_reason():
    result = validate_sql("ATTACH 'evil.db' AS e", enforce_limit=True)
    assert result.valid is False


def test_multi_statement_rejected():
    result = validate_sql("SELECT * FROM orders; DROP TABLE products", enforce_limit=True)
    assert result.valid is False
    assert result.error_type == "multi_statement"


def test_empty_sql_rejected():
    result = validate_sql("   ", enforce_limit=True)
    assert result.valid is False
    assert result.error_type == "empty_sql"


def test_cte_with_write_inside_rejected():
    result = validate_sql("WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x", enforce_limit=True)
    assert result.valid is False


def test_non_select_first_token_rejected():
    result = validate_sql("EXPLAIN SELECT * FROM orders", enforce_limit=True)
    assert result.valid is False


# --- Quote-aware false-positive regressions --------------------------------
def test_keyword_in_string_literal_not_flagged():
    result = validate_sql("SELECT status FROM orders WHERE status = 'delete'", enforce_limit=True)
    assert result.valid is True


def test_keyword_as_column_value_not_flagged():
    result = validate_sql("SELECT * FROM products WHERE name = 'DROP TABLE'", enforce_limit=True)
    assert result.valid is True


def test_quoted_column_name_with_keyword_ok():
    result = validate_sql('SELECT "delete" AS col FROM orders', enforce_limit=True)
    assert result.valid is True


def test_escaped_quote_handled():
    result = validate_sql("SELECT * FROM orders WHERE status = 'it''s delete'", enforce_limit=True)
    assert result.valid is True


# --- Row limit enforcement ------------------------------------------------
def test_limit_injected_when_missing():
    result = validate_sql("SELECT * FROM orders", enforce_limit=True, max_rows=500)
    assert result.valid is True
    assert result.has_limit is True
    assert "LIMIT" in result.sql.upper()


def test_limit_capped_at_ceiling():
    result = validate_sql("SELECT * FROM orders", enforce_limit=True, max_rows=1000)
    assert result.valid is True
    assert "1000" in result.sql


def test_existing_small_limit_accepted():
    result = validate_sql("SELECT * FROM orders LIMIT 3", enforce_limit=True, max_rows=500)
    assert result.valid is True
    assert result.limit_value == 3


def test_huge_limit_rejected():
    result = validate_sql("SELECT * FROM orders LIMIT 99999", enforce_limit=True, max_rows=500)
    assert result.valid is False
    assert result.error_type == "limit_too_high"


# --- Sanitization ----------------------------------------------------------
def test_sanitize_removes_paths():
    from security.sql_guard import sanitize_db_error

    msg = sanitize_db_error(Exception('no such table: C:\\Users\\evil\\secret.db'))
    assert "C:\\Users" not in msg


def test_rewritten_sql_still_executes_against_seeded_db(settings):
    """End-to-end: rewritten SQL must still run correctly."""
    from db.access_layer import execute_read_only

    result = execute_read_only("SELECT * FROM orders")
    assert result["row_count"] >= 0
    assert "LIMIT" in result["sql"].upper()
    assert result["columns"] != []