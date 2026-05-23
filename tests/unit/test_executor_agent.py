"""Tests for the Executor agent flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.agents.executor.main import ExecutorAgent
from apps.agents.shared.events import Recommendation
from apps.control_plane.policy_engine import Decision, PolicyEngine

pytestmark = pytest.mark.unit


def _rec(**overrides) -> Recommendation:
    base = dict(
        site_id="frankfurt",
        kind="workload_migration",
        target_device_ids=["frankfurt-h1-r07-srv03"],
        parameters={
            "moves": [
                {"workload_id": "wl-frankfurt-h1-r07-srv03",
                 "from_rack_id": "frankfurt-h1-r07",
                 "to_rack_id": "frankfurt-h1-r08",
                 "power_w": 600.0, "thermal_kw": 0.54},
            ],
            "solver_status": "OPTIMAL",
        },
        estimated_impact={"power_redistributed_w": 600.0},
        confidence=0.85,
        requires_human_approval=False,
    )
    base.update(overrides)
    return Recommendation(**base)


@dataclass
class _FakeRedis:
    pushed: list[str] = field(default_factory=list)
    trims: list[Any] = field(default_factory=list)

    async def lpush(self, key: str, value: str) -> int:
        self.pushed.append(value)
        return len(self.pushed)

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        self.trims.append((key, start, stop))


@dataclass
class _FakeBus:
    published: list[tuple[str, Any]] = field(default_factory=list)
    _client: _FakeRedis = field(default_factory=_FakeRedis)

    async def publish(self, topic: str, event: Any) -> int:
        self.published.append((topic, event))
        return 1

    async def close(self) -> None:
        pass


@pytest.fixture
def executor(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("SITE_ID", "frankfurt")
    # Disable mocks so action handlers report an HTTP failure deterministically.
    monkeypatch.delenv("MOCKS_BASE_URL", raising=False)

    agent = ExecutorAgent()
    bus = _FakeBus()
    agent.bus = bus
    from apps.agents.shared.ts_client import TimescaleStore
    agent.ts = TimescaleStore.from_env()      # not connected → KPI snapshot returns {}
    # Use an empty engine so self-flag is the only mechanism affecting decisions.
    agent.policy = PolicyEngine.from_yaml("policies: []")
    return agent, bus


async def test_approved_recommendation_publishes_action_executed(executor, monkeypatch) -> None:
    agent, bus = executor

    # Force the action handler to return a deterministic success without HTTP.
    async def _fake_handler(rec, action_id):
        return True, {"applied": True, "action_id": action_id}

    import apps.agents.executor.actions as actions
    monkeypatch.setattr(actions, "handle_workload_migration", _fake_handler)
    monkeypatch.setattr(actions, "HANDLERS", {"workload_migration": _fake_handler})

    await agent.handle(_rec())

    action_pubs = [p for p in bus.published if p[0] == "actions.executed"]
    assert action_pubs
    topic, ev = action_pubs[0]
    payload = ev.model_dump()
    assert payload["success"] is True
    assert payload["response_payload"]["applied"] is True
    # Persisted to Redis list.
    assert bus._client.pushed


async def test_denied_recommendation_records_but_does_not_execute(executor) -> None:
    agent, bus = executor
    agent.policy = PolicyEngine.from_yaml(
        """
        policies:
          - id: freeze
            kind: change_freeze
            parameters: {enabled: true}
        """
    )

    await agent.handle(_rec())

    # No actions.executed publish for a denied rec.
    assert not [p for p in bus.published if p[0] == "actions.executed"]
    # But we DO persist a denied marker for the audit trail.
    assert bus._client.pushed
    import json
    persisted = json.loads(bus._client.pushed[0])
    assert persisted["success"] is False
    assert persisted["response_payload"]["denied"] is True


async def test_needs_human_publishes_to_needs_human_topic(executor) -> None:
    agent, bus = executor
    await agent.handle(_rec(requires_human_approval=True))

    nh_pubs = [p for p in bus.published if p[0] == "actions.needs_human"]
    assert nh_pubs
    # No execution should have happened.
    assert not [p for p in bus.published if p[0] == "actions.executed"]


async def test_unknown_kind_is_recorded_as_denied(executor) -> None:
    agent, bus = executor
    await agent.handle(_rec(kind="not_a_real_kind"))
    # Recorded as denied, not executed.
    assert not [p for p in bus.published if p[0] == "actions.executed"]
    assert bus._client.pushed


def test_parse_accepts_dict_and_pydantic() -> None:
    rec = _rec()
    assert ExecutorAgent._parse(rec) is rec
    assert ExecutorAgent._parse(rec.model_dump(mode="json")) is not None
    assert ExecutorAgent._parse(None) is None
    assert ExecutorAgent._parse({"not": "valid"}) is None
