"""Connection registry and multi-database tests.

The PostgreSQL tests run against a real server when one is reachable at
``DATAPILOT_TEST_PG_URL`` (or the default local test port) and skip otherwise,
so the suite stays green on a machine without Postgres while still being able
to prove the engine really works.

Bring one up with:
    docker run -d --name datapilot-pg -e POSTGRES_PASSWORD=datapilot \
      -e POSTGRES_USER=datapilot -e POSTGRES_DB=shop -p 55432:5432 postgres:16-alpine
"""

from __future__ import annotations

import os

import pytest

from db import connections as registry
from db.connections import (
    DEMO_CONNECTION_ID,
    POSTGRES_KIND,
    SQLITE_KIND,
    Connection,
    ConnectionError_,
    normalize_postgres_url,
    redact_target,
)

PG_URL = os.environ.get(
    "DATAPILOT_TEST_PG_URL", "postgresql://datapilot:datapilot@localhost:55432/shop"
)


def _postgres_available() -> bool:
    try:
        from db import postgres

        postgres.check_connection(normalize_postgres_url(PG_URL))
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(), reason="no PostgreSQL server reachable for this test"
)


# --- URL handling ----------------------------------------------------------

def test_postgres_url_gets_an_explicit_driver():
    """Without a driver SQLAlchemy reaches for psycopg2, which isn't installed."""
    assert normalize_postgres_url("postgresql://u:p@h:5432/d").startswith("postgresql+psycopg://")
    assert normalize_postgres_url("postgres://u:p@h:5432/d").startswith("postgresql+psycopg://")


def test_existing_driver_is_left_alone():
    url = "postgresql+psycopg://u:p@h:5432/d"
    assert normalize_postgres_url(url) == url


def test_a_non_postgres_url_is_rejected():
    with pytest.raises(ConnectionError_):
        normalize_postgres_url("mysql://u:p@h/d")


def test_password_never_reaches_the_client():
    shown = redact_target(POSTGRES_KIND, "postgresql+psycopg://admin:hunter2@db.internal:5432/shop")
    assert "hunter2" not in shown
    assert "psycopg" not in shown  # internal driver detail, not user-facing
    assert shown == "postgresql://admin@db.internal:5432/shop"


def test_sqlite_location_is_just_the_filename(tmp_path):
    assert redact_target(SQLITE_KIND, str(tmp_path / "nested" / "mydata.db")) == "mydata.db"


# --- session routing -------------------------------------------------------

def test_sessions_default_to_the_demo_database():
    assert registry.get_session_connection("never-seen").id == DEMO_CONNECTION_ID


def test_session_switch_and_reset(settings):
    from store import session_store

    session_id = session_store.create_session("switch")
    connection = registry.register_connection("Scratch", SQLITE_KIND, str(settings.db_path))
    try:
        registry.set_session_connection(session_id, connection.id)
        assert registry.get_session_connection(session_id).id == connection.id

        registry.reset_session_connection(session_id)
        assert registry.get_session_connection(session_id).id == DEMO_CONNECTION_ID
    finally:
        registry.remove_connection(connection.id)
        session_store.delete_session(session_id)


def test_a_session_is_never_stranded_on_a_deleted_connection(settings):
    """Deleting a connection must not break sessions still pointing at it."""
    from store import session_store

    session_id = session_store.create_session("stranded")
    connection = registry.register_connection("Temp", SQLITE_KIND, str(settings.db_path))
    try:
        registry.set_session_connection(session_id, connection.id)
        registry.remove_connection(connection.id)
        assert registry.get_session_connection(session_id).id == DEMO_CONNECTION_ID
    finally:
        session_store.delete_session(session_id)


def test_the_demo_connection_cannot_be_removed():
    with pytest.raises(ConnectionError_):
        registry.remove_connection(DEMO_CONNECTION_ID)


# --- dialect correctness ---------------------------------------------------

def test_guard_rewrites_limit_in_the_target_dialect():
    from security.sql_guard import validate_sql

    # A dialect mismatch would emit SQL the server can't run.
    for dialect in ("sqlite", "postgres"):
        result = validate_sql("SELECT * FROM orders", max_rows=50, dialect=dialect)
        assert result.valid
        assert "LIMIT 50" in result.sql.upper()


def test_postgres_specific_syntax_parses_only_as_postgres():
    from security.sql_guard import validate_sql

    # ILIKE is Postgres-only; parsing it as SQLite would misread the query.
    result = validate_sql("SELECT * FROM customers WHERE name ILIKE 'a%'", dialect="postgres")
    assert result.valid


# --- live PostgreSQL -------------------------------------------------------

@pytest.fixture(scope="module")
def pg_connection():
    return Connection(id="pgtest", name="pg", kind=POSTGRES_KIND, target=normalize_postgres_url(PG_URL))


@requires_postgres
def test_postgres_schema_discovery_matches_the_sqlite_shape(pg_connection):
    from db.schema_discovery import discover_schema_for

    schema = discover_schema_for(pg_connection)
    assert schema["tables"], "no tables discovered"
    table = schema["tables"][0]
    # Same keys the SQLite path produces — callers must not be able to tell.
    assert set(table) == {"name", "columns", "primary_keys", "foreign_keys"}
    assert set(table["columns"][0]) == {"name", "type", "nullable", "pk"}


@requires_postgres
def test_postgres_foreign_keys_feed_the_er_diagram(pg_connection):
    from db.schema_discovery import discover_schema_for
    from viz.mermaid_builder import build_er_diagram

    mermaid = build_er_diagram(discover_schema_for(pg_connection))
    assert mermaid.startswith("erDiagram")
    assert "||--o{" in mermaid, "no relationships rendered from Postgres foreign keys"


@requires_postgres
def test_postgres_numerics_arrive_as_numbers(pg_connection):
    """NUMERIC comes back as Decimal; left alone it serialises to a string and
    the chart recommender reads the measure as a category."""
    from db.access_layer import execute_read_only

    result = execute_read_only(
        "SELECT category, SUM(price) AS total FROM products GROUP BY category",
        connection=pg_connection,
    )
    totals = [row[1] for row in result["rows"]]
    assert totals and all(isinstance(v, (int, float)) for v in totals), totals


@requires_postgres
def test_postgres_writes_are_blocked(pg_connection):
    from db.access_layer import QueryExecutionError, execute_read_only

    for sql in ("DROP TABLE customers", "DELETE FROM orders", "UPDATE products SET price = 0"):
        with pytest.raises(QueryExecutionError):
            execute_read_only(sql, connection=pg_connection)


@requires_postgres
def test_postgres_row_ceiling_is_enforced(pg_connection):
    from db.access_layer import execute_read_only

    result = execute_read_only(
        "SELECT * FROM order_items", connection=pg_connection, max_rows=2
    )
    assert len(result["rows"]) <= 2


@requires_postgres
def test_pii_masking_applies_on_postgres_too(pg_connection):
    from db.access_layer import execute_read_only

    result = execute_read_only("SELECT name, email FROM customers", connection=pg_connection)
    assert "email_redacted" in result["columns"]
    idx = result["columns"].index("email_redacted")
    assert all(row[idx] == "***" for row in result["rows"])


# --- HTTP surface ----------------------------------------------------------

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


def test_connections_endpoint_reports_the_active_database(client):
    body = client.get("/api/connections").json()
    assert body["active_id"] == DEMO_CONNECTION_ID
    demo = [c for c in body["connections"] if c["id"] == DEMO_CONNECTION_ID][0]
    assert demo["is_demo"] is True


def test_a_bad_postgres_url_is_rejected_before_it_is_saved(client):
    r = client.post("/api/connections/postgres", json={"name": "nope", "url": "mysql://u:p@h/d"})
    assert r.status_code == 400
    assert not any(c["name"] == "nope" for c in client.get("/api/connections").json()["connections"])


def test_an_unreachable_postgres_is_rejected(client):
    r = client.post(
        "/api/connections/postgres",
        json={"name": "dead", "url": "postgresql://u:p@127.0.0.1:1/none"},
    )
    assert r.status_code in (400, 501)
    assert not any(c["name"] == "dead" for c in client.get("/api/connections").json()["connections"])


def test_the_demo_connection_cannot_be_deleted_over_http(client):
    assert client.delete(f"/api/connections/{DEMO_CONNECTION_ID}").status_code == 400


@requires_postgres
def test_switching_a_session_changes_which_database_it_queries(client):
    """The same SQL must resolve against different databases per session."""
    session_id = client.post("/api/sessions", json={"title": "route"}).json()["session_id"]
    created = client.post("/api/connections/postgres", json={"name": "Shop", "url": PG_URL})
    connection_id = created.json()["connection"]["id"]
    try:
        client.post(f"/api/sessions/{session_id}/connection", json={"connection_id": connection_id})
        listing = client.get("/api/connections", params={"session_id": session_id}).json()
        assert listing["active_id"] == connection_id
        # Credentials must never reach the browser.
        assert "datapilot:datapilot" not in str(listing)

        pg_tables = {
            t["name"] for t in client.get(f"/api/sessions/{session_id}/schema").json()["tables"]
        }
        client.post(f"/api/sessions/{session_id}/connection/reset")
        demo_tables = {
            t["name"] for t in client.get(f"/api/sessions/{session_id}/schema").json()["tables"]
        }
        assert "inventory" in demo_tables, "reset did not return to the demo database"
        assert "inventory" not in pg_tables
    finally:
        client.delete(f"/api/connections/{connection_id}")
        client.delete(f"/api/sessions/{session_id}")
