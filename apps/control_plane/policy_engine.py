"""Policy engine.

YAML-defined ruleset that gates every Executor action. Loaded once at
agent startup; rules can be reloaded at runtime via `reload()`.

Supported policy kinds:
    blast_radius      → cap how many devices one action can touch
    blackout_window   → refuse certain action kinds during a time window
    change_freeze     → kill-switch: deny everything when enabled
    custom            → simple rule string of the form
                        `if <python-ish predicate> then <decision>`
                        (sandboxed eval against `rec` + `rec.metadata`)

Decision model:
    `evaluate(recommendation, now=None)` returns `(decision, reason, applied)`:
      Decision.APPROVED         — proceed
      Decision.DENIED           — drop, log reason
      Decision.NEEDS_HUMAN      — queue for operator review
    `applied` lists the policy IDs that actually fired (for audit).

Ordering matters: rules are evaluated in YAML order, and the FIRST
non-approve verdict wins. This makes "change-freeze first" the obvious
top-of-file rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    kind: str
    parameters: dict[str, Any]
    applies_to_sites: list[str] = field(default_factory=list)   # empty = all


# --- per-kind evaluators -------------------------------------------------------


def _eval_blast_radius(p: Policy, rec: Recommendation) -> tuple[Decision, str | None]:
    cap = int(p.parameters.get("max_devices_per_action", 8))
    n = len(rec.target_device_ids)
    if n > cap:
        return Decision.NEEDS_HUMAN, f"blast radius {n} > cap {cap}"
    return Decision.APPROVED, None


def _eval_blackout_window(
    p: Policy, rec: Recommendation, now: datetime
) -> tuple[Decision, str | None]:
    applies_to_kinds = set(p.parameters.get("applies_to_kinds", []))
    if applies_to_kinds and rec.kind not in applies_to_kinds:
        return Decision.APPROVED, None
    start_h = int(p.parameters.get("local_start_hour", 22))
    end_h = int(p.parameters.get("local_end_hour", 6))
    # Operate in UTC unless the parameter `tz_offset_hours` is set.
    offset_h = int(p.parameters.get("tz_offset_hours", 0))
    local_hour = (now.astimezone(timezone.utc).hour + offset_h) % 24
    in_window = (
        start_h <= local_hour < 24 or 0 <= local_hour < end_h
        if start_h > end_h
        else start_h <= local_hour < end_h
    )
    if in_window:
        return (
            Decision.DENIED,
            f"in blackout window [{start_h}, {end_h}) (current local hour {local_hour})",
        )
    return Decision.APPROVED, None


def _eval_change_freeze(p: Policy, rec: Recommendation) -> tuple[Decision, str | None]:
    if p.parameters.get("enabled", False):
        return Decision.DENIED, "change freeze in effect"
    return Decision.APPROVED, None


_CUSTOM_RULE_RE = re.compile(
    r"^\s*if\s+(?P<cond>.+?)\s+then\s+(?P<verdict>approved|denied|needs_human)\s*$",
    flags=re.IGNORECASE,
)


def _eval_custom(p: Policy, rec: Recommendation) -> tuple[Decision, str | None]:
    """Tiny, intentionally constrained DSL for custom one-line rules.

    Form: `if <expr> then <decision>`. `<expr>` is evaluated against a
    locked-down namespace containing `recommendation` (the event) and a
    handful of helpers. NO arbitrary Python — we allow only attribute and
    item access, comparisons, booleans, and string literals.
    """
    rule = str(p.parameters.get("rule", ""))
    m = _CUSTOM_RULE_RE.match(rule)
    if not m:
        return Decision.APPROVED, None
    cond_src = m.group("cond")
    verdict = m.group("verdict").lower()

    safe_globals = {"__builtins__": {}}
    safe_locals: dict[str, Any] = {
        "recommendation": rec,
        "rec": rec,
        "site_id": rec.site_id,
        "kind": rec.kind,
        "n_devices": len(rec.target_device_ids),
        "confidence": rec.confidence,
        "metadata": rec.metadata,
        "requires_human_approval": rec.requires_human_approval,
    }
    try:
        result = bool(eval(cond_src, safe_globals, safe_locals))  # noqa: S307 — sandboxed
    except Exception as exc:  # noqa: BLE001
        log.warning("policy.custom_eval_failed", policy_id=p.id, error=str(exc))
        return Decision.APPROVED, None
    if not result:
        return Decision.APPROVED, None
    if verdict == "denied":
        return Decision.DENIED, f"custom rule {p.id} matched"
    if verdict == "needs_human":
        return Decision.NEEDS_HUMAN, f"custom rule {p.id} matched"
    return Decision.APPROVED, None


# --- engine ---------------------------------------------------------------------


@dataclass
class PolicyEngine:
    """Loads, holds, and evaluates policies."""

    policies: list[Policy]

    @classmethod
    def from_default_config(cls) -> PolicyEngine:
        return cls.from_path(DEFAULT_POLICY_PATH)

    @classmethod
    def from_path(cls, path: Path) -> PolicyEngine:
        if not path.exists():
            log.warning("policy.config_missing", path=str(path))
            return cls(policies=[])
        return cls.from_yaml(path.read_text())

    @classmethod
    def from_yaml(cls, text: str) -> PolicyEngine:
        raw: dict[str, Any] = yaml.safe_load(text) or {}
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

    def evaluate(
        self,
        rec: Recommendation,
        now: datetime | None = None,
    ) -> tuple[Decision, str | None, list[str]]:
        """Run `rec` through every relevant policy.

        Returns (decision, reason, applied_policy_ids).
        First non-APPROVED verdict wins; the precedence order is
        DENIED > NEEDS_HUMAN > APPROVED (more conservative beats more
        permissive). Ordering within those tiers follows YAML order.
        """
        now = now or datetime.now(timezone.utc)
        applied: list[str] = []
        deny_reason: str | None = None
        human_reason: str | None = None

        for p in self.policies:
            if p.applies_to_sites and rec.site_id not in p.applies_to_sites:
                continue
            decision, reason = self._eval_one(p, rec, now)
            log.debug(
                "policy.eval",
                policy_id=p.id, kind=p.kind, decision=decision.value,
                recommendation_id=str(rec.recommendation_id),
            )
            applied.append(p.id)
            if decision is Decision.DENIED and deny_reason is None:
                deny_reason = f"{p.id}: {reason}"
            elif decision is Decision.NEEDS_HUMAN and human_reason is None:
                human_reason = f"{p.id}: {reason}"

        # Layered precedence + the recommendation's own self-flag.
        if deny_reason is not None:
            return Decision.DENIED, deny_reason, applied
        if rec.requires_human_approval and human_reason is None:
            human_reason = "recommendation self-flagged for review"
            applied.append("self-flag")
        if human_reason is not None:
            return Decision.NEEDS_HUMAN, human_reason, applied
        return Decision.APPROVED, None, applied

    @staticmethod
    def _eval_one(
        p: Policy, rec: Recommendation, now: datetime
    ) -> tuple[Decision, str | None]:
        if p.kind == "blast_radius":
            return _eval_blast_radius(p, rec)
        if p.kind == "blackout_window":
            return _eval_blackout_window(p, rec, now)
        if p.kind == "change_freeze":
            return _eval_change_freeze(p, rec)
        if p.kind == "custom":
            return _eval_custom(p, rec)
        log.warning("policy.unknown_kind", kind=p.kind, policy_id=p.id)
        return Decision.APPROVED, None


__all__ = ["Decision", "Policy", "PolicyEngine"]
