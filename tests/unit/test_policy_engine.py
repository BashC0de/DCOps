"""Tests for the policy engine."""

from __future__ import annotations

import pytest

from apps.agents.shared.events import Recommendation
from apps.control_plane.policy_engine import Decision, PolicyEngine


@pytest.mark.unit
def test_default_policy_loads() -> None:
    engine = PolicyEngine.from_default_config()
    assert len(engine.policies) >= 1


@pytest.mark.unit
def test_recommendation_requiring_human_returns_needs_human() -> None:
    engine = PolicyEngine.from_default_config()
    rec = Recommendation(
        site_id="frankfurt",
        kind="workload_migration",
        target_device_ids=["frankfurt-h1-r01-srv01"],
        parameters={"target_rack": "frankfurt-h1-r05"},
        estimated_impact={"thermal_drop_c": 3.0},
        confidence=0.8,
        requires_human_approval=True,
    )
    decision, _ = engine.evaluate(rec)
    assert decision == Decision.NEEDS_HUMAN


@pytest.mark.unit
def test_normal_recommendation_approved_in_skeleton() -> None:
    engine = PolicyEngine.from_default_config()
    rec = Recommendation(
        site_id="frankfurt",
        kind="workload_migration",
        target_device_ids=["d1"],
        parameters={},
        estimated_impact={"thermal_drop_c": 2.0},
        confidence=0.7,
    )
    decision, _ = engine.evaluate(rec)
    # Skeleton engine approves by default; tighten this assertion in Week 8.
    assert decision == Decision.APPROVED
