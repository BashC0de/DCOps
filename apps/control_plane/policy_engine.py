"""Policy engine.

Purpose:
    YAML-defined ruleset that every Executor action is checked against
    before it runs. Rules express:
      - blast radius caps (no action affecting more than N devices)
      - blackout windows (no automated migrations between 22:00-06:00 local)
      - change-freeze (toggle that disables all automated actions)
      - per-site overrides

Ships: Week 8 (see ROADMAP.md).

Decision model:
    `evaluate(recommendation)` returns one of:
      Decision.APPROVED         — proceed
      Decision.DENIED           — drop, log reason
      Decision.NEEDS_HUMAN      — queue for operator review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from apps.agents.shared.events import Recommendation
from apps.agents.shared.logging import get_logger

log = get_logger(__name__)

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "policies.default.yml"


class Decision(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"
    NEEDS_HUMAN = "needs_human"


@dataclass
class Policy:
    """A single rule loaded from YAML."""

    id: str
    kind: str                       # blast_radius | blackout_window | change_freeze | custom
    parameters: dict[str, Any]
    applies_to_sites: list[str] = field(default_factory=list)   # empty = all


@dataclass
class PolicyEngine:
    """Loads, holds, and evaluates policies."""

    policies: list[Policy]

    @classmethod
    def from_default_config(cls) -> PolicyEngine:
        if not DEFAULT_POLICY_PATH.exists():
            log.warning("policy.default_missing", path=str(DEFAULT_POLICY_PATH))
            return cls(policies=[])
        raw: dict[str, Any] = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
        policies = [
            Policy(
                id=p["id"],
                kind=p["kind"],
                parameters=p.get("parameters", {}),
                applies_to_sites=list(p.get("applies_to_sites", [])),
            )
            for p in raw.get("policies", [])
        ]
        return cls(policies=policies)

    def evaluate(self, rec: Recommendation) -> tuple[Decision, str | None]:
        """Run `rec` through every relevant policy. Returns (decision, reason)."""
        # TODO(week-8): implement per-kind evaluators. Skeleton always approves.
        for p in self.policies:
            if p.applies_to_sites and rec.site_id not in p.applies_to_sites:
                continue
            log.debug("policy.eval", policy=p.id, kind=p.kind, recommendation_id=str(rec.recommendation_id))
        if rec.requires_human_approval:
            return Decision.NEEDS_HUMAN, "recommendation flagged for human review"
        return Decision.APPROVED, None


__all__ = ["Decision", "Policy", "PolicyEngine"]
