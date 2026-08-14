"""API-level tests using FastAPI TestClient against the real app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_schema_endpoint():
    r = client.get("/api/schema")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["tables"]]
    assert "orders" in names


def test_query_endpoint():
    r = client.post("/api/query", json={"sql": "SELECT COUNT(*) AS c FROM orders"})
    assert r.status_code == 200
    assert r.json()["columns"] == ["c"]


def test_query_endpoint_rejects_write():
    r = client.post("/api/query", json={"sql": "DELETE FROM orders"})
    assert r.status_code == 400
    assert r.json()["detail"]["type"] == "unsafe_statement"


def test_session_lifecycle():
    r = client.post("/api/sessions", json={"title": "t"})
    sid = r.json()["session_id"]
    assert r.status_code == 200

    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert "messages" in r.json()

    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200


def test_chat_sse_offline():
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "final" in r.text


def test_chat_sse_data_query():
    r = client.post("/api/chat", json={"message": "top 3 products by revenue"})
    body = r.text
    assert "event: final" in body
    assert "chart" in body


def test_dashboard_pin_flow():
    r = client.post("/api/sessions", json={"title": "dash"})
    sid = r.json()["session_id"]

    r = client.post(
        "/api/dashboard/pin",
        json={"session_id": sid, "kind": "chart", "title": "Rev", "payload": {"type": "bar"}},
    )
    assert r.status_code == 200
    item_id = r.json()["item_id"]

    r = client.get(f"/api/dashboard/{sid}")
    assert len(r.json()["items"]) == 1

    r = client.delete(f"/api/dashboard/item/{item_id}")
    assert r.status_code == 200

    r = client.get(f"/api/dashboard/{sid}")
    assert len(r.json()["items"]) == 0