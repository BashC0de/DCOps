"""Tests for the cross-site correlator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.control_plane.cross_site_correlator import (
    CrossSiteCorrelator,
    _build_candidate,
    run_correlator,
)

pytestmark = pytest.mark.unit


def _pred(*, site: str, kind: str, prob: float = 0.95, device: str = "d-1") -> dict[str, Any]:
    return {
        "site_id": site,
        "failure_kind": kind,
        "probability": prob,
        "device_id": device,
    }


def test_below_confidence_floor_never_propagates() -> None:
    c = CrossSiteCorrelator()
    for _ in range(10):
        out = c.record_prediction(_pred(site="frankfurt", kind="gpu_ecc_drift", prob=0.5))
    assert out == []
    assert c.hit_count("frankfurt", "gpu_ecc_drift") == 0


def test_propagates_after_threshold(monkeypatch) -> None:
    # Lower threshold to 2 for a deterministic, fast test.
    import apps.control_plane.cross_site_correlator as cc
    monkeypatch.setattr(cc, "_PROPAGATION_THRESHOLD", 2)

    c = CrossSiteCorrelator()
    out1 = c.record_prediction(_pred(site="frankfurt", kind="gpu_ecc_drift", device="d1"))
    assert out1 == []
    out2 = c.record_prediction(_pred(site="frankfurt", kind="gpu_ecc_drift", device="d2"))
    assert out2 != []
    origin, kind, devices = out2[0]
    assert origin == "frankfurt"
    assert kind == "gpu_ecc_drift"
    assert set(devices) == {"d1", "d2"}


def test_cooldown_prevents_repropagation(monkeypatch) -> None:
    import apps.control_plane.cross_site_correlator as cc
    monkeypatch.setattr(cc, "_PROPAGATION_THRESHOLD", 2)
    monkeypatch.setattr(cc, "_REPROPAGATE_COOLDOWN_S", 10_000)

    c = CrossSiteCorrelator()
    c.record_prediction(_pred(site="frankfurt", kind="gpu_ecc_drift"))
    first = c.record_prediction(_pred(site="frankfurt", kind="gpu_ecc_drift"))
    assert first != []
    # Third predict — still over threshold but cooldown blocks.
    third = c.record_prediction(_pred(site="frankfurt", kind="gpu_ecc_drift"))
    assert third == []


def test_build_candidate_marshals_fields() -> None:
    cand = _build_candidate(
        origin_site_id="frankfurt",
        target_site_id="singapore",
        failure_kind="gpu_ecc_drift",
        confidence=0.92,
        occurrence_count=4,
        sample_device_ids=["d1", "d2"],
    )
    payload = cand.model_dump()
    assert payload["origin_site_id"] == "frankfurt"
    assert payload["target_site_id"] == "singapore"
    assert payload["site_id"] == "singapore"  # BusEvent inherits site_id from target
    assert payload["origin_confidence"] == pytest.approx(0.92)
    assert payload["sample_device_ids"] == ["d1", "d2"]


# --- end-to-end against a fake bus -------------------------------------------


@dataclass
class _FakeRedis:
    lists: dict[str, list[str]] = field(default_factory=dict)

    async def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        items = self.lists.get(key, [])
        if stop == -1:
            self.lists[key] = items[start:]
        else:
            self.lists[key] = items[start : stop + 1]


@dataclass
class _FakeBus:
    inbound: list[dict[str, Any]] = field(default_factory=list)
    published: list[tuple[str, Any]] = field(default_factory=list)
    _client: _FakeRedis = field(default_factory=_FakeRedis)

    async def publish(self, topic: str, event: Any) -> int:
        self.published.append((topic, event))
        return 1

    async def subscribe(self, pattern: str):  # noqa: ANN201
        _ = pattern
        for event in self.inbound:
            yield event

    async def close(self) -> None:
        pass


async def test_run_correlator_publishes_to_other_sites(monkeypatch) -> None:
    import apps.control_plane.cross_site_correlator as cc
    monkeypatch.setattr(cc, "_PROPAGATION_THRESHOLD", 2)
    monkeypatch.setattr(cc, "_FEDERATION_SITES", ("frankfurt", "singapore", "mumbai"))

    bus = _FakeBus(
        inbound=[
            _pred(site="frankfurt", kind="gpu_ecc_drift", device="d1"),
            _pred(site="frankfurt", kind="gpu_ecc_drift", device="d2"),
        ]
    )
    await run_correlator(bus=bus, correlator=CrossSiteCorrelator())

    targets = sorted(t for t, _ in bus.published)
    # Two non-origin sites → two candidate publishes.
    assert targets == [
        "federation.rule_candidate.mumbai",
        "federation.rule_candidate.singapore",
    ]
    # Each candidate carries the origin + kind.
    payloads = [ev.model_dump() for _, ev in bus.published]
    assert all(p["origin_site_id"] == "frankfurt" for p in payloads)
    assert all(p["failure_kind"] == "gpu_ecc_drift" for p in payloads)
    # Persisted under the target site's list.
    assert "federation:candidates:singapore" in bus._client.lists
    assert "federation:candidates:mumbai" in bus._client.lists
