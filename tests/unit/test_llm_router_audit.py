"""Tests that the LLM router publishes audit + budget events through the bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.agents.shared.llm_router import LLMRouter, ModelTier, TaskClass

pytestmark = pytest.mark.unit


@dataclass
class _FakeBus:
    """Records calls to publish/publish_stream."""

    pub: list[tuple[str, Any]] = field(default_factory=list)
    stream: list[tuple[str, Any]] = field(default_factory=list)

    async def publish(self, topic: str, event: Any) -> int:
        self.pub.append((topic, event))
        return 1

    async def publish_stream(self, key: str, event: Any, maxlen: int | None = 100_000) -> str:
        self.stream.append((key, event))
        return "0-0"


async def test_audit_record_published_to_stream(fake_backend) -> None:
    bus = _FakeBus()
    router = LLMRouter(agent_name="forensic", backend=fake_backend, event_bus=bus)
    fake_backend.replies = ["ok"]

    await router.call(
        task_class=TaskClass.RCA,
        system="s",
        messages=[{"role": "user", "content": "u"}],
    )

    assert len(bus.stream) == 1
    stream_key, record = bus.stream[0]
    assert stream_key == "audit.events"
    payload = record.model_dump()
    assert payload["agent"] == "forensic"
    assert payload["backend"] == "fake"
    assert payload["task_class"] == "rca"


async def test_no_audit_when_no_bus_attached(fake_backend) -> None:
    # Backwards compat: tests/agents that don't pass a bus still work.
    router = LLMRouter(agent_name="x", backend=fake_backend)
    fake_backend.replies = ["ok"]
    result = await router.call(
        task_class=TaskClass.CLASSIFY,
        system="s",
        messages=[{"role": "user", "content": "u"}],
    )
    assert result.text == "ok"


async def test_budget_exceeded_emits_event_and_downgrades(fake_backend, monkeypatch) -> None:
    """When the Anthropic budget is breached, route to fast tier and emit alert."""
    # Pretend the backend is Anthropic (so the budget path engages).
    fake_backend.name = "anthropic"
    bus = _FakeBus()
    router = LLMRouter(
        agent_name="forensic",
        daily_budget_usd=0.0,  # immediate breach
        backend=fake_backend,
        event_bus=bus,
    )
    # Make the router think we already spent above budget.
    router._spent_today_usd = 1.0  # noqa: SLF001

    fake_backend.replies = ["downgraded reply"]
    result = await router.call(
        task_class=TaskClass.DEEP_REASONING,
        system="s",
        messages=[{"role": "user", "content": "u"}],
        force_tier=ModelTier.SONNET,
    )

    assert result.downgraded is True
    assert result.tier_used == ModelTier.HAIKU
    # budget.exceeded event published exactly once.
    budget_pubs = [p for p in bus.pub if p[0] == LLMRouter.BUDGET_TOPIC]
    assert len(budget_pubs) == 1
    payload = budget_pubs[0][1].model_dump()
    assert payload["agent"] == "forensic"
    assert payload["backend"] == "anthropic"


async def test_budget_event_emitted_once_per_day(fake_backend) -> None:
    fake_backend.name = "anthropic"
    bus = _FakeBus()
    router = LLMRouter(
        agent_name="x",
        daily_budget_usd=0.0,
        backend=fake_backend,
        event_bus=bus,
    )
    router._spent_today_usd = 1.0  # noqa: SLF001
    fake_backend.replies = ["a", "b"]

    await router.call(task_class=TaskClass.CLASSIFY, system="s", messages=[{"role": "user", "content": "x"}])
    await router.call(task_class=TaskClass.CLASSIFY, system="s", messages=[{"role": "user", "content": "x"}])

    budget_pubs = [p for p in bus.pub if p[0] == LLMRouter.BUDGET_TOPIC]
    assert len(budget_pubs) == 1
