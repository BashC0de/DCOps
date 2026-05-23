"""Tests for the benchmark report renderer."""

from __future__ import annotations

import pytest

from benchmarks.report import TARGETS, _aggregate, _verdict, render

pytestmark = pytest.mark.unit


def _result(**overrides):
    base = dict(
        name="gen_gpu_gpu_ecc_runaway_frankfurt_0",
        category="gpu",
        site_id="frankfurt",
        started_at="2026-05-23T00:00:00+00:00",
        finished_at="2026-05-23T00:01:00+00:00",
        detected=True,
        detection_latency_sec=30.0,
        rca_top1_match=True,
        actions_proposed=["workload_migration"],
        actions_executed=[],
        expected_actions=["workload_migration"],
        candidate_propagated=False,
        llm_cost_usd=0.01,
        error=None,
        incident_id=None,
        rca_text=None,
        predictions=[],
    )
    base.update(overrides)
    return base


def test_verdict_thresholds() -> None:
    assert _verdict(0.9, "> 0.80") == "ok"
    assert _verdict(0.7, "> 0.80") == "miss"
    assert _verdict(45.0, "< 60") == "ok"
    assert _verdict(90.0, "< 60") == "miss"
    assert _verdict(0.01, "< $0.02") == "ok"
    assert _verdict(0.05, "< $0.02") == "miss"


def test_aggregate_empty() -> None:
    agg = _aggregate([])
    for key in TARGETS.keys():
        assert agg[key] is None


def test_aggregate_basic_stats() -> None:
    results = [
        _result(name="a", detected=True, rca_top1_match=True, detection_latency_sec=20.0, llm_cost_usd=0.005),
        _result(name="b", detected=True, rca_top1_match=False, detection_latency_sec=50.0, llm_cost_usd=0.010),
        _result(name="c", detected=False, rca_top1_match=False, detection_latency_sec=None, llm_cost_usd=0.0),
    ]
    agg = _aggregate(results)
    assert agg["predictive_precision"] == pytest.approx(2 / 3)
    assert agg["rca_top1"] == pytest.approx(1 / 3)
    assert agg["mttd"] == pytest.approx(35.0)
    assert agg["llm_cost_per_incident"] == pytest.approx(0.005)


def test_aggregate_action_recall() -> None:
    results = [
        _result(expected_actions=["workload_migration"], actions_proposed=["workload_migration"]),
        _result(expected_actions=["fan_speed_adjust"], actions_proposed=["workload_migration"]),
        _result(expected_actions=[], actions_proposed=[]),  # trivially satisfied
    ]
    agg = _aggregate(results)
    # 1.0 + 0.0 + 1.0 = 2.0 / 3 = 0.667
    assert agg["action_recall"] == pytest.approx(2 / 3)


def test_aggregate_federation_propagation() -> None:
    results = [
        _result(name="gen_federated_gpu_ecc_frankfurt", candidate_propagated=True),
        _result(name="gen_federated_gpu_ecc_singapore", candidate_propagated=False),
        _result(name="gen_gpu_runaway_frankfurt_0"),
    ]
    agg = _aggregate(results)
    # 1 of 2 federated scenarios propagated.
    assert agg["federation_propagation"] == pytest.approx(0.5)


def test_render_produces_valid_html() -> None:
    results = [
        _result(name="a", detected=True, llm_cost_usd=0.01),
        _result(name="b", detected=False, llm_cost_usd=0.0, category="psu"),
    ]
    html_str = render(results)
    assert "<!doctype html>" in html_str
    assert "Ran 2 scenarios" in html_str
    assert "Headline metrics" in html_str
    # Each scenario appears in the per-scenario detail.
    assert "<code>a</code>" in html_str
    assert "<code>b</code>" in html_str


def test_render_no_scenarios_still_renders() -> None:
    html_str = render([])
    assert "Ran 0 scenarios" in html_str
