"""KG grounding — validate LLM outputs against ground truth.

Two validators:

    validate_metrics(metric_names)
        Returns the subset of names that are NOT in the frozen
        `CanonicalMetric` enum. Empty list = all good.

    KGValidator.validate_device_ids(device_ids)
        Returns the subset of device IDs that don't exist in Neo4j.
        Delegates to a `KnowledgeGraph` (or any object exposing the same
        async methods). When `kg=None`, all validation methods are no-ops.

Used by:
    - Forensic: every device_id named in an IncidentReport must exist.
    - Operator: every metric name in NL-to-SQL output must be canonical.
    - Vision: every device_id in an addendum must exist.

When a hallucination is detected, callers typically re-prompt the model
with the list of unknown identifiers via `format_grounding_errors()` so
the structured retry loop can revise.
"""

from __future__ import annotations

from typing import Any, Protocol

from apps.agents.shared.logging import get_logger
from apps.ingestion.schema import CanonicalMetric

log = get_logger(__name__)


class _KGLike(Protocol):
    """Anything with the two validation methods. `KnowledgeGraph` satisfies it."""

    enabled: bool

    async def validate_device_ids(self, device_ids: list[str]) -> list[str]: ...
    async def validate_site_ids(self, site_ids: list[str]) -> list[str]: ...


def validate_metrics(metric_names: list[str]) -> list[str]:
    """Return the metric names NOT in `CanonicalMetric`."""
    canonical = {m.value for m in CanonicalMetric}
    unknown = [m for m in metric_names if m not in canonical]
    if unknown:
        log.warning("quality.kg_grounding.unknown_metrics", unknown=unknown)
    return unknown


class KGValidator:
    """Thin adapter around a `KnowledgeGraph`-shaped object.

    Pass a connected `KnowledgeGraph` (or a test fake exposing the same
    methods) at construction. If None, all validation methods become no-ops
    so the validator is safe to wire into agents whose KG connection isn't
    up yet (early-week scaffolding, missing infrastructure).
    """

    def __init__(self, kg: _KGLike | Any = None) -> None:
        self._kg = kg

    @property
    def enabled(self) -> bool:
        if self._kg is None:
            return False
        return bool(getattr(self._kg, "enabled", True))

    async def validate_device_ids(self, device_ids: list[str]) -> list[str]:
        if self._kg is None or not device_ids:
            return []
        try:
            missing = await self._kg.validate_device_ids(device_ids)
        except Exception as exc:  # noqa: BLE001
            log.warning("quality.kg_grounding.kg_query_failed", error=str(exc))
            return []
        if missing:
            log.warning("quality.kg_grounding.unknown_devices", unknown=missing)
        return missing

    async def validate_site_ids(self, site_ids: list[str]) -> list[str]:
        if self._kg is None or not site_ids:
            return []
        if not hasattr(self._kg, "validate_site_ids"):
            return []
        try:
            return await self._kg.validate_site_ids(site_ids)
        except Exception as exc:  # noqa: BLE001
            log.warning("quality.kg_grounding.kg_query_failed", error=str(exc))
            return []


def format_grounding_errors(
    *,
    unknown_metrics: list[str] | None = None,
    unknown_devices: list[str] | None = None,
    unknown_sites: list[str] | None = None,
) -> str | None:
    """Build a correction hint to feed back to the model. None = all good."""
    bits: list[str] = []
    if unknown_metrics:
        bits.append(
            "Unknown metric names (not in the canonical catalog): "
            + ", ".join(unknown_metrics)
        )
    if unknown_devices:
        bits.append(
            "Unknown device IDs (not present in the knowledge graph): "
            + ", ".join(unknown_devices)
        )
    if unknown_sites:
        bits.append("Unknown site IDs: " + ", ".join(unknown_sites))
    if not bits:
        return None
    return (
        "Your response references identifiers that do not exist:\n"
        + "\n".join(f"- {b}" for b in bits)
        + "\nFix the response using only identifiers from the provided context."
    )


__all__ = [
    "KGValidator",
    "validate_metrics",
    "format_grounding_errors",
]
