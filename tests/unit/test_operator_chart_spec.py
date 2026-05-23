"""Tests for the polished Plotly chart-spec generator."""

from __future__ import annotations

import pytest

from apps.agents.operator.main import OperatorAgent

pytestmark = pytest.mark.unit


def test_returns_none_for_empty_rows() -> None:
    assert OperatorAgent._chart_spec([]) is None


def test_returns_none_when_no_recognized_shape() -> None:
    # Rows with neither time+value nor cat+value should yield None.
    spec = OperatorAgent._chart_spec([{"foo": True}])
    assert spec is None


def test_single_line_for_time_value() -> None:
    rows = [
        {"time": "2026-05-23T00:00:00Z", "value_num": 1.0},
        {"time": "2026-05-23T00:01:00Z", "value_num": 2.0},
    ]
    spec = OperatorAgent._chart_spec(rows, question="trend")
    assert spec is not None
    assert spec["data"][0]["type"] == "scatter"
    assert spec["data"][0]["y"] == [1.0, 2.0]
    assert spec["layout"]["title"] == "trend"
    assert spec["layout"]["xaxis"]["title"] == "time"
    assert spec["layout"]["yaxis"]["title"] == "value_num"


def test_multi_line_for_time_category_value() -> None:
    rows = [
        {"time": "t1", "site_id": "frankfurt", "value_num": 10.0},
        {"time": "t1", "site_id": "singapore", "value_num": 20.0},
        {"time": "t2", "site_id": "frankfurt", "value_num": 11.0},
        {"time": "t2", "site_id": "singapore", "value_num": 22.0},
    ]
    spec = OperatorAgent._chart_spec(rows, question="compare")
    assert spec is not None
    series_names = {trace["name"] for trace in spec["data"]}
    assert series_names == {"frankfurt", "singapore"}
    fr_trace = next(t for t in spec["data"] if t["name"] == "frankfurt")
    assert fr_trace["y"] == [10.0, 11.0]


def test_bar_for_category_plus_value() -> None:
    rows = [
        {"rack_id": "fra-h1-r01", "peak_c": 32.4},
        {"rack_id": "fra-h1-r02", "peak_c": 31.8},
    ]
    spec = OperatorAgent._chart_spec(rows, question="hottest")
    assert spec is not None
    assert spec["data"][0]["type"] == "bar"
    assert spec["data"][0]["x"] == ["fra-h1-r01", "fra-h1-r02"]
    assert spec["data"][0]["y"] == [32.4, 31.8]
