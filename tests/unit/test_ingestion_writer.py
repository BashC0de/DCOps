"""Tests for the TimescaleDB writer task in apps/ingestion/main.py."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

pytestmark = pytest.mark.unit


@dataclass
class _FakeBus:
    """Yields a fixed sequence of telemetry dicts then stops."""

    payloads: list[dict[str, Any]] = field(default_factory=list)
    pubsub_started: bool = False

    async def subscribe(self, pattern: str):  # noqa: ANN201
        self.pubsub_started = True
        _ = pattern
        for p in self.payloads:
            yield p
        # Drop dead — let the consumer task complete.


@dataclass
class _FakeTimescale:
    enabled: bool = True
    inserts: list[list[dict[str, Any]]] = field(default_factory=list)

    async def insert_telemetry(self, events: list[dict[str, Any]]) -> int:
        # Take a copy because the writer reuses its batch list.
        self.inserts.append(list(events))
        return len(events)


def _ev(metric: str = "cpu.temp.celsius", value: float = 62.0) -> dict[str, Any]:
    return {
        "timestamp": "2026-05-23T00:00:00+00:00",
        "site_id": "frankfurt",
        "hall_id": "frankfurt-h1",
        "rack_id": "frankfurt-h1-r01",
        "device_id": "frankfurt-h1-r01-srv01",
        "device_type": "server",
        "metric": metric,
        "value": value,
        "unit": "celsius",
        "severity": "info",
        "metadata": {},
    }


async def test_writer_flushes_on_batch_size(monkeypatch) -> None:
    import apps.ingestion.main as ingestion

    # Small batch limit so we flush deterministically.
    monkeypatch.setattr(ingestion, "WRITER_FLUSH_MAX", 3)
    monkeypatch.setattr(ingestion, "WRITER_FLUSH_INTERVAL_S", 60.0)  # don't fire ticker

    bus = _FakeBus(payloads=[_ev() for _ in range(7)])
    ts = _FakeTimescale()

    task = asyncio.create_task(ingestion.run_writer(bus, ts))  # type: ignore[arg-type]
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # 7 events / batch=3 → two size-flushes (3+3) + one shutdown-flush of 1
    flushed = [n for batch in ts.inserts for n in batch]
    assert len(flushed) == 7
    assert len(ts.inserts) >= 2


async def test_writer_no_op_when_disabled() -> None:
    import apps.ingestion.main as ingestion

    bus = _FakeBus(payloads=[_ev()])
    ts = _FakeTimescale(enabled=False)

    # Returns immediately without subscribing.
    await ingestion.run_writer(bus, ts)  # type: ignore[arg-type]
    assert bus.pubsub_started is False
    assert ts.inserts == []


async def test_writer_flushes_on_interval_tick(monkeypatch) -> None:
    """The ticker flushes a partial batch when the interval elapses."""
    import apps.ingestion.main as ingestion

    monkeypatch.setattr(ingestion, "WRITER_FLUSH_MAX", 100)  # never hit
    monkeypatch.setattr(ingestion, "WRITER_FLUSH_INTERVAL_S", 0.05)

    bus = _FakeBus(payloads=[_ev() for _ in range(2)])
    ts = _FakeTimescale()

    task = asyncio.create_task(ingestion.run_writer(bus, ts))  # type: ignore[arg-type]
    await asyncio.sleep(0.25)  # give the ticker time
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    total = sum(len(b) for b in ts.inserts)
    assert total == 2
