"""Tests for the offline engine and chart recommender."""

from __future__ import annotations

import pytest

from llm.offline import answer_offline, classify_intent
from viz.recommender import build_chart_spec, recommend_chart


# --- Offline engine --------------------------------------------------------
def test_casual_greeting(settings):
    reply = answer_offline("hello", settings)
    assert reply["mode"] == "offline"
    assert "DataPilot" in reply["answer"]


def test_top_products_query(settings):
    reply = answer_offline("top 5 products by revenue", settings)
    assert reply["mode"] == "offline"
    assert reply["chart"] is not None
    assert reply["sql"] is not None
    assert "Monitor" in reply["answer"]


def test_er_diagram_offline(settings):
    reply = answer_offline("draw me the ER diagram", settings)
    assert reply["diagram"] is not None
    assert reply["diagram"]["mermaid"].startswith("erDiagram")


def test_trend_offline(settings):
    reply = answer_offline("show monthly revenue trend", settings)
    assert reply["chart"] is not None


def test_classify_intent():
    assert classify_intent("hi")["intent"] == "casual"
    assert classify_intent("what is the revenue?")["intent"] == "analytical"


# --- Chart recommender -----------------------------------------------------
def test_temporal_data_line():
    rows = [[f"2024-0{i}", i * 10] for i in range(1, 7)]
    assert recommend_chart(["month", "revenue"], rows) == "line"


def test_categorical_bar():
    rows = [["A", 100], ["B", 200], ["C", 150]]
    assert recommend_chart(["category", "revenue"], rows) == "bar"


def test_hint_honored():
    rows = [["A", 100], ["B", 200]]
    spec = build_chart_spec(["cat", "val"], rows, chart_type="pie")
    assert spec["type"] == "pie"


def test_single_column_kpi():
    rows = [[5]]
    assert recommend_chart(["count"], rows) == "kpi"


def test_two_numeric_scatter():
    rows = [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11, 12], [13, 14], [15, 16], [17, 18], [19, 20]]
    assert recommend_chart(["x", "y"], rows) in {"scatter", "bar"}