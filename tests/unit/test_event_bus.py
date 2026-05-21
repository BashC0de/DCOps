"""Tests for the Redis event bus wrapper."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from apps.agents.shared.events import PredictedFailure
from apps.agents.shared.event_bus import EventBus


@pytest.mark.unit
async def test_publish_subscribe_roundtrip(fake_redis: Any) -> None:
    bus = EventBus.__new__(EventBus)
    bus._url = "fake"  # type: ignore[attr-defined]
    bus._client = fake_redis  # type: ignore[attr-defined]

    event = PredictedFailure(
        site_id="frankfurt",
        device_id="frankfurt-h1-r01-srv01-gpu1",
        device_type="gpu",
        failure_kind="gpu_ecc_runaway",
        probability=0.82,
        horizon_hours=12.0,
        evidence={"ecc_count": 50_000},
    )

    received: list[PredictedFailure] = []

    async def consume() -> None:
        async for ev in bus.subscribe("predictions.failure", PredictedFailure):
            received.append(ev)
            break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await bus.publish("predictions.failure", event)
    await asyncio.wait_for(consumer, timeout=2.0)

    assert len(received) == 1
    assert received[0].device_id == event.device_id
    assert received[0].probability == pytest.approx(0.82)
