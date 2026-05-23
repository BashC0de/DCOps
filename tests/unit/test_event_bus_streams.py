"""Tests for the new `publish_stream` method on EventBus."""

from __future__ import annotations

from typing import Any

import fakeredis.aioredis
import pytest

from apps.agents.shared.event_bus import EventBus
from apps.agents.shared.events import BudgetExceeded

pytestmark = pytest.mark.unit


@pytest.fixture
async def patched_bus(monkeypatch) -> Any:
    """An EventBus that connects to fakeredis."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    bus = EventBus("redis://placeholder")
    monkeypatch.setattr(bus, "_client", fake)
    try:
        yield bus
    finally:
        await fake.aclose()


async def test_publish_stream_writes_entry(patched_bus) -> None:
    event = BudgetExceeded(
        site_id="frankfurt",
        agent="forensic",
        spent_usd=5.01,
        budget_usd=5.0,
        backend="anthropic",
    )
    entry_id = await patched_bus.publish_stream("audit.events", event)
    assert isinstance(entry_id, str)
    assert "-" in entry_id  # <ms>-<seq>

    # Stream length increments.
    length = await patched_bus._client.xlen("audit.events")
    assert length == 1


async def test_publish_stream_carries_event_json(patched_bus) -> None:
    event = BudgetExceeded(
        site_id="frankfurt",
        agent="forensic",
        spent_usd=5.01,
        budget_usd=5.0,
        backend="anthropic",
    )
    entry_id = await patched_bus.publish_stream("audit.events", event)
    entries = await patched_bus._client.xrange("audit.events", min=entry_id, max=entry_id)
    assert entries
    _, fields = entries[0]
    assert "data" in fields
    assert '"agent":"forensic"' in fields["data"]
