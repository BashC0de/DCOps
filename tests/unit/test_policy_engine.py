"""Tests for the policy engine.

Loads policies inline via `from_yaml` so we don't depend on file paths.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.agents.shared.events import Recommendation
from apps.control_plane.policy_engine import Decision, PolicyEngine

pytestmark = pytest.mark.unit


def _rec(**overrides) -> Recommendation:
    base = dict(
        site_id="frankfurt",
        kind="workload_migration",
        target_device_ids=["frankfurt-h1-r07-srv03"],
        parameters={"moves": []},
        estimated_impact={"power_redistributed_w": 1000.0},
        confidence=0.85,
        requires_human_approval=False,
    )
    base.update(overrides)
    return Recommendation(**base)


# --- default config loads -----------------------------------------------------


def test_default_policy_loads() -> None:
    engine = PolicyEngine.from_default_config()
    assert len(engine.policies) >= 1


# --- blast_radius -------------------------------------------------------------


def test_blast_radius_approves_below_cap() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: br
            kind: blast_radius
            parameters: {max_devices_per_action: 5}
        """
    )
    decision, _reason, applied = engine.evaluate(_rec(target_device_ids=["a", "b", "c"]))
    assert decision is Decision.APPROVED
    assert "br" in applied


def test_blast_radius_needs_human_above_cap() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: br
            kind: blast_radius
            parameters: {max_devices_per_action: 3}
        """
    )
    rec = _rec(target_device_ids=["a", "b", "c", "d", "e"])
    decision, reason, _ = engine.evaluate(rec)
    assert decision is Decision.NEEDS_HUMAN
    assert "blast radius 5 > cap 3" in (reason or "")


# --- blackout_window ----------------------------------------------------------


def test_blackout_window_denies_inside_window() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: night
            kind: blackout_window
            parameters:
              local_start_hour: 22
              local_end_hour: 6
              applies_to_kinds: [workload_migration]
        """
    )
    now = datetime(2026, 5, 23, 2, 30, tzinfo=timezone.utc)
    decision, reason, _ = engine.evaluate(_rec(), now=now)
    assert decision is Decision.DENIED
    assert "blackout window" in (reason or "")


def test_blackout_window_approves_outside_window() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: night
            kind: blackout_window
            parameters:
              local_start_hour: 22
              local_end_hour: 6
              applies_to_kinds: [workload_migration]
        """
    )
    now = datetime(2026, 5, 23, 14, 0, tzinfo=timezone.utc)
    decision, _, _ = engine.evaluate(_rec(), now=now)
    assert decision is Decision.APPROVED


def test_blackout_window_skips_other_kinds() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: night
            kind: blackout_window
            parameters:
              local_start_hour: 22
              local_end_hour: 6
              applies_to_kinds: [workload_migration]
        """
    )
    now = datetime(2026, 5, 23, 2, 30, tzinfo=timezone.utc)
    decision, _, _ = engine.evaluate(_rec(kind="fan_speed_adjust"), now=now)
    assert decision is Decision.APPROVED


# --- change_freeze ------------------------------------------------------------


def test_change_freeze_denies_when_enabled() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: freeze
            kind: change_freeze
            parameters: {enabled: true}
        """
    )
    decision, reason, _ = engine.evaluate(_rec())
    assert decision is Decision.DENIED
    assert "change freeze" in (reason or "")


def test_change_freeze_approves_when_disabled() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: freeze
            kind: change_freeze
            parameters: {enabled: false}
        """
    )
    decision, _, _ = engine.evaluate(_rec())
    assert decision is Decision.APPROVED


# --- custom -------------------------------------------------------------------


def test_custom_rule_flags_low_confidence_for_human() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: low-conf
            kind: custom
            parameters:
              rule: "if confidence < 0.5 then needs_human"
        """
    )
    decision, _, _ = engine.evaluate(_rec(confidence=0.3))
    assert decision is Decision.NEEDS_HUMAN

    decision, _, _ = engine.evaluate(_rec(confidence=0.9))
    assert decision is Decision.APPROVED


def test_custom_rule_invalid_syntax_falls_back_to_approve() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: bad
            kind: custom
            parameters:
              rule: "not a valid rule string"
        """
    )
    decision, _, _ = engine.evaluate(_rec())
    assert decision is Decision.APPROVED


# --- self-flag ---------------------------------------------------------------


def test_self_flag_for_human_review() -> None:
    engine = PolicyEngine.from_yaml("policies: []")
    rec = _rec(requires_human_approval=True)
    decision, reason, applied = engine.evaluate(rec)
    assert decision is Decision.NEEDS_HUMAN
    assert "self-flag" in applied


# --- per-site override -------------------------------------------------------


def test_policy_skipped_when_site_doesnt_match() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: only-mumbai
            kind: change_freeze
            parameters: {enabled: true}
            applies_to_sites: [mumbai]
        """
    )
    decision, _, applied = engine.evaluate(_rec(site_id="frankfurt"))
    assert decision is Decision.APPROVED
    assert "only-mumbai" not in applied

    decision, _, _ = engine.evaluate(_rec(site_id="mumbai"))
    assert decision is Decision.DENIED


# --- precedence --------------------------------------------------------------


def test_deny_beats_needs_human() -> None:
    engine = PolicyEngine.from_yaml(
        """
        policies:
          - id: br
            kind: blast_radius
            parameters: {max_devices_per_action: 1}
          - id: freeze
            kind: change_freeze
            parameters: {enabled: true}
        """
    )
    rec = _rec(target_device_ids=["a", "b", "c"])
    decision, _, _ = engine.evaluate(rec)
    assert decision is Decision.DENIED   # freeze (DENIED) wins
