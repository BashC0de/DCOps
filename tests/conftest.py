"""Shared pytest fixtures.

Mocks the Redis bus, Anthropic SDK, and database clients so unit tests can
run without docker. Integration tests opt in via the `integration` marker
and require the `dev` profile to be up.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import fakeredis.aioredis
import pytest


@pytest.fixture
async def fake_redis() -> AsyncIterator[Any]:
    """In-memory Redis suitable for EventBus tests."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def telemetry_event_dict() -> dict[str, Any]:
    """A minimal valid TelemetryEvent payload (dict form)."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "site_id": "frankfurt",
        "hall_id": "frankfurt-h1",
        "rack_id": "frankfurt-h1-r01",
        "device_id": "frankfurt-h1-r01-srv01",
        "device_type": "server",
        "metric": "cpu.temp.celsius",
        "value": 62.5,
        "unit": "celsius",
        "severity": "info",
        "metadata": {},
    }


@pytest.fixture
def mock_anthropic_response() -> dict[str, Any]:
    """Canned Anthropic Messages API response shape for unit tests."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "stubbed response"}],
        "model": "claude-haiku-4-5-20251001",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
