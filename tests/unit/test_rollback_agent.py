"""Tests for the Rollback Monitor agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from apps.agents.rollback.main import RollbackAgent, is_regression
from apps.agents.shared.events import ActionExecuted

pytestmark = pytest.mark.unit


@dataclass
class _FakeBus:
    published: list[tuple[str, Any]] = field(default_factory=list)
    _client: Any = None

    async def publish(self, topic: str, event: Any) -> int:
        self.published.append((topic, event))
        return 1

    async def close(self) -> None:
        pass


def _action(*, success: bool = True, pre: dict[str, float] | None = None, **extra) -> ActionExecuted:
    # `pre is None` (not `pre or ...`) so `{}` is honored.
    if pre is None:
        pre = {"env.outlet.celsius": 28.0, "fan.rpm": 4200.0}
    return ActionExecuted(
        site_id="frankfurt",
        recommendation_id=uuid4(),
        action_id=uuid4(),
        success=success,
        response_payload=extra.get("response_payload", {"applied": True}),
        pre_action_kpis=pre,
        metadata={"kind": "workload_migration"},
    )


# --- is_regression ------------------------------------------------------------


def test_is_regression_lower_is_better() -> None:
    # +20% on a "lower is better" metric beats the 10% threshold.
    assert is_regression("env.outlet.celsius", 25.0, 30.0, threshold=0.1) is True
    # +5% under threshold = OK.
    assert is_regression("env.outlet.celsius", 25.0, 26.0, threshold=0.1) is False
    # Improvement (lower post) is not a regression.
    assert is_regression("env.outlet.celsius", 30.0, 25.0, threshold=0.1) is False


def test_is_regression_higher_is_better() -> None:
    # Big fan-RPM drop = regression.
    assert is_regression("fan.rpm", 4200.0, 3500.0, threshold=0.1) is True
    # Modest dip = OK.
    assert is_regression("fan.rpm", 4200.0, 4100.0, threshold=0.1) is False
    # Rise = not a regression.
    assert is_regression("fan.rpm", 4200.0, 4500.0, threshold=0.1) is False


# --- handle() ---------------------------------------------------------------


@pytest.fixture
def rollback_agent(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("SITE_ID", "frankfurt")
    agent = RollbackAgent()
    bus = _FakeBus()
    agent.bus = bus
    from apps.agents.shared.ts_client import TimescaleStore
    agent.ts = TimescaleStore.from_env()  # not connected
    agent._inflight = set()
    return agent, bus


async def test_handle_skips_unsuccessful_actions(rollback_agent) -> None:
    agent, bus = rollback_agent
    await agent.handle(_action(success=False))
    assert agent._inflight == set()


async def test_handle_skips_when_no_pre_kpis(rollback_agent) -> None:
    agent, bus = rollback_agent
    await agent.handle(_action(pre={}))
    assert agent._inflight == set()


async def test_handle_schedules_verification(rollback_agent, monkeypatch) -> None:
    agent, bus = rollback_agent
    # Speed up the observation window for the test.
    import apps.agents.rollback.main as rm
    monkeypatch.setattr(rm, "_OBSERVATION_S", 0.01)

    act = _action()
    await agent.handle(act)
    assert str(act.action_id) in agent._inflight
    # Drain the scheduled task so the test doesn't leak it.
    import asyncio
    await asyncio.sleep(0.1)
    assert str(act.action_id) not in agent._inflight


async def test_verify_commit_when_no_regression(rollback_agent, monkeypatch) -> None:
    agent, bus = rollback_agent
    # Force post-KPI snapshot to return same values as pre.
    async def _snapshot(_event):
        return {"env.outlet.celsius": 28.0, "fan.rpm": 4200.0}
    monkeypatch.setattr(agent, "_snapshot_post_kpis", _snapshot)

    await agent._verify(_action())
    # No rolled_back publish.
    assert not [p for p in bus.published if p[0] == "actions.rolled_back"]


async def test_verify_reverts_when_thermal_regresses(rollback_agent, monkeypatch) -> None:
    agent, bus = rollback_agent
    # Post temp rises 25% — beats 10% threshold.
    async def _snapshot(_event):
        return {"env.outlet.celsius": 35.0, "fan.rpm": 4200.0}
    monkeypatch.setattr(agent, "_snapshot_post_kpis", _snapshot)

    # Don't actually hit HTTP for the revert.
    async def _fake_revert(original_action_id, *, reason):
        return True, {"reverted": True, "reason": reason}
    import apps.agents.executor.actions as exec_actions
    monkeypatch.setattr(exec_actions, "revert", _fake_revert)

    await agent._verify(_action())
    rb_pubs = [p for p in bus.published if p[0] == "actions.rolled_back"]
    assert rb_pubs
    _topic, event = rb_pubs[0]
    payload = event.model_dump()
    assert "env.outlet.celsius" in payload["reason"]
    assert payload["metadata"]["revert_ok"] is True
