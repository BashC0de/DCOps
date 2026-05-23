"""Tests for the POST /query route.

We drive it with a fake bus that records publishes and returns a scripted
QueryResult on `query.result` after a short delay — simulating Operator.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app

pytestmark = pytest.mark.unit


@dataclass
class _ScriptedBus:
    """Buffers publishes; replays them to subscribers.

    When `auto_reply` is set, every publish to a `query.<rid>` topic
    triggers a synthetic `QueryResult` on `query.result` after a small
    delay — emulating the Operator agent.
    """

    publishes: list[tuple[str, Any]] = field(default_factory=list)
    _subscribers: dict[str, list[asyncio.Queue]] = field(default_factory=dict)
    _client: Any = None
    auto_reply: dict[str, Any] | None = None

    async def publish(self, topic: str, event: Any) -> int:
        # Decode the Pydantic event to dict to match real EventBus.subscribe.
        payload: dict[str, Any]
        if hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json")
        elif hasattr(event, "model_dump_json"):
            payload = json.loads(event.model_dump_json())
        elif isinstance(event, dict):
            payload = event
        else:
            payload = dict(event)
        self.publishes.append((topic, payload))

        # Deliver to matching subscribers (pattern is simplified — full
        # `query.*` is the only one our route uses).
        for pat, queues in self._subscribers.items():
            if _pattern_matches(pat, topic):
                for q in queues:
                    await q.put(payload)

        if self.auto_reply and topic.startswith("query.") and topic != "query.result":
            # Simulate Operator: respond on query.result with the same request_id.
            await asyncio.sleep(0.01)
            reply = dict(self.auto_reply)
            reply["request_id"] = payload.get("request_id")
            await self.publish("query.result", reply)
        return 1

    async def subscribe(self, pattern: str):  # noqa: ANN201
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(pattern, []).append(q)
        try:
            while True:
                payload = await q.get()
                yield payload
        finally:
            try:
                self._subscribers[pattern].remove(q)
            except ValueError:
                pass

    async def close(self) -> None:
        pass


def _pattern_matches(pattern: str, topic: str) -> bool:
    """Tiny glob — supports trailing `*` only."""
    if pattern.endswith("*"):
        return topic.startswith(pattern[:-1])
    return pattern == topic


def test_query_route_503_when_no_bus() -> None:
    app = create_app()
    with TestClient(app) as c:
        app.state.bus = None
        r = c.post("/query", json={"question": "what?"})
        assert r.status_code == 503


def test_query_route_round_trip_with_scripted_operator(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_QUERY_TIMEOUT_S", "5")
    # Re-import the route module so the new env value is picked up.
    import importlib

    import apps.api.routes.query as query_route
    importlib.reload(query_route)

    app = create_app()
    bus = _ScriptedBus(
        auto_reply={
            "answer_text": "rack 7 was hottest at 32.4°C",
            "sql_executed": "SELECT ...",
            "chart_spec": None,
            "sources": [],
        }
    )
    with TestClient(app) as c:
        app.state.bus = bus
        r = c.post("/query", json={"question": "which racks are hot?"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answer_text"] == "rack 7 was hottest at 32.4°C"
        # We should have published a query.<rid> message.
        topics = [t for t, _ in bus.publishes]
        assert any(t.startswith("query.") and t != "query.result" for t in topics)
        # And the published payload includes the question + request_id.
        first_pub = next(p for t, p in bus.publishes if t.startswith("query.") and t != "query.result")
        assert first_pub["question"] == "which racks are hot?"
        assert "request_id" in first_pub


def test_query_route_504_when_operator_silent(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_QUERY_TIMEOUT_S", "0.3")
    import importlib

    import apps.api.routes.query as query_route
    importlib.reload(query_route)

    app = create_app()
    bus = _ScriptedBus(auto_reply=None)  # no reply
    with TestClient(app) as c:
        app.state.bus = bus
        r = c.post("/query", json={"question": "anything?"})
        assert r.status_code == 504


async def test_wait_for_result_filters_by_request_id() -> None:
    """Direct test of _wait_for_result: a wrong-id event is skipped."""
    import apps.api.routes.query as query_route

    bus = _ScriptedBus()
    target_rid = str(uuid4())
    ready = asyncio.Event()
    waiter = asyncio.create_task(
        query_route._wait_for_result(bus, target_rid, ready, timeout_s=1.0)
    )
    await asyncio.wait_for(ready.wait(), timeout=1.0)

    # First publish a noise event (wrong rid), then the real one.
    await bus.publish("query.result", {"request_id": str(uuid4()), "answer_text": "noise"})
    await bus.publish("query.result", {"request_id": target_rid, "answer_text": "match"})

    result = await asyncio.wait_for(waiter, timeout=1.0)
    assert result["answer_text"] == "match"
