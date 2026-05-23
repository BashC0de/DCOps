"""Tests for the POST /vision/analyze route."""

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
    """Buffers publishes; auto-replies with a synthetic vision addendum."""

    publishes: list[tuple[str, Any]] = field(default_factory=list)
    _subscribers: dict[str, list[asyncio.Queue]] = field(default_factory=dict)
    _client: Any = None
    auto_reply: dict[str, Any] | None = None

    async def publish(self, topic: str, event: Any) -> int:
        if hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json")
        elif hasattr(event, "model_dump_json"):
            payload = json.loads(event.model_dump_json())
        elif isinstance(event, dict):
            payload = event
        else:
            payload = dict(event)
        self.publishes.append((topic, payload))

        for pat, queues in self._subscribers.items():
            if _matches(pat, topic):
                for q in queues:
                    await q.put(payload)

        if (
            self.auto_reply
            and topic == "vision.request"
            and isinstance(payload, dict)
        ):
            await asyncio.sleep(0.01)
            reply = dict(self.auto_reply)
            reply.setdefault("metadata", {})
            reply["metadata"] = {**reply["metadata"], "request_id": payload.get("request_id")}
            await self.publish("incidents.vision_addendum", reply)
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


def _matches(pattern: str, topic: str) -> bool:
    if pattern.endswith("*"):
        return topic.startswith(pattern[:-1])
    return pattern == topic


def test_vision_route_503_when_no_bus() -> None:
    app = create_app()
    with TestClient(app) as c:
        app.state.bus = None
        r = c.post("/vision/analyze", json={"context": "rack 7 LED off"})
    assert r.status_code == 503


def test_vision_round_trip_with_scripted_agent(monkeypatch) -> None:
    monkeypatch.setenv("VISION_QUERY_TIMEOUT_S", "5")
    import importlib

    import apps.api.routes.vision as vroute
    importlib.reload(vroute)

    app = create_app()
    bus = _ScriptedBus(
        auto_reply={
            "site_id": "frankfurt",
            "finding_summary": "amber LED on PSU 2",
            "affected_device_ids": ["frankfurt-h1-r07-srv03"],
            "severity": "error",
            "confidence": 0.85,
            "evidence_observations": ["amber LED visible"],
        }
    )
    with TestClient(app) as c:
        app.state.bus = bus
        r = c.post(
            "/vision/analyze",
            json={"context": "rack 7 LED off", "images": ["AAAA"]},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["finding_summary"] == "amber LED on PSU 2"
    # Vision request was published with a request_id.
    pubs = [p for p in bus.publishes if p[0] == "vision.request"]
    assert pubs
    payload = pubs[0][1]
    assert payload["context"] == "rack 7 LED off"
    assert isinstance(payload["request_id"], str)


def test_vision_route_504_when_agent_silent(monkeypatch) -> None:
    monkeypatch.setenv("VISION_QUERY_TIMEOUT_S", "0.3")
    import importlib

    import apps.api.routes.vision as vroute
    importlib.reload(vroute)

    app = create_app()
    bus = _ScriptedBus(auto_reply=None)
    with TestClient(app) as c:
        app.state.bus = bus
        r = c.post("/vision/analyze", json={"context": "x"})
    assert r.status_code == 504


async def test_matches_strictly_filters_by_request_id() -> None:
    import apps.api.routes.vision as vroute

    bus = _ScriptedBus()
    target_rid = str(uuid4())
    ready = asyncio.Event()
    waiter = asyncio.create_task(
        vroute._wait_for_addendum(bus, target_rid, ready, timeout_s=1.0)
    )
    await asyncio.wait_for(ready.wait(), timeout=1.0)

    # Wrong request_id — should be skipped.
    await bus.publish("incidents.vision_addendum",
                      {"finding_summary": "other", "metadata": {"request_id": str(uuid4())}})
    # Right request_id — should satisfy.
    await bus.publish("incidents.vision_addendum",
                      {"finding_summary": "match", "metadata": {"request_id": target_rid}})

    result = await asyncio.wait_for(waiter, timeout=1.0)
    assert result["finding_summary"] == "match"
