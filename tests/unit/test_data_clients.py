"""Tests for KnowledgeGraph / TimescaleStore / VectorStore graceful degradation.

These tests verify that the wrappers can be constructed without their
backing services being available, and that all methods return safe
defaults in that state. Live integration tests live elsewhere.
"""

from __future__ import annotations

import pytest

from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.ts_client import TimescaleStore
from apps.agents.shared.vector_client import VectorStore

pytestmark = pytest.mark.unit


# --- KnowledgeGraph -------------------------------------------------------------

async def test_kg_disabled_until_connect() -> None:
    kg = KnowledgeGraph.from_env()
    assert kg.enabled is False
    assert await kg.validate_device_ids(["d1"]) == []
    assert await kg.validate_site_ids(["s1"]) == []
    assert await kg.dependency_subgraph("d1") == []
    assert await kg.register_incident(
        incident_id="i1",
        opened_at="2026-05-22T00:00:00Z",
        severity="warn",
        affected_device_ids=["d1"],
    ) is False


async def test_kg_close_is_safe_when_unconnected() -> None:
    kg = KnowledgeGraph.from_env()
    await kg.close()  # no-op, must not raise


async def test_kg_session_returns_none_when_unconnected() -> None:
    kg = KnowledgeGraph.from_env()
    assert kg.session() is None


# --- TimescaleStore -------------------------------------------------------------

async def test_ts_disabled_until_connect() -> None:
    ts = TimescaleStore.from_env()
    assert ts.enabled is False
    assert await ts.recent_telemetry("d1") == []
    assert await ts.execute_select("SELECT 1") == []
    assert await ts.insert_telemetry([{"timestamp": "x", "metric": "y"}]) == 0


async def test_ts_execute_select_refuses_non_select_after_connect_attempt() -> None:
    ts = TimescaleStore.from_env()
    # Even without a live pool, the validator runs and raises on bad SQL.
    # We sidestep by constructing a fake "connected" state minimally:
    class _FakePool:
        async def __aenter__(self): raise NotImplementedError
        async def __aexit__(self, *a): pass
    ts._pool = object()  # type: ignore[assignment]  # noqa: SLF001

    with pytest.raises(ValueError):
        await ts.execute_select("INSERT INTO telemetry VALUES (1)")
    with pytest.raises(ValueError):
        await ts.execute_select("DROP TABLE x")
    with pytest.raises(ValueError):
        await ts.execute_select("UPDATE telemetry SET x=1")
    # Restore to disabled state.
    ts._pool = None  # noqa: SLF001


async def test_ts_close_is_safe_when_unconnected() -> None:
    ts = TimescaleStore.from_env()
    await ts.close()


# --- VectorStore ----------------------------------------------------------------

async def test_vec_disabled_until_connect() -> None:
    vec = VectorStore.from_env()
    assert vec.enabled is False
    assert vec.client is None
    assert await vec.get_or_create_collection("any") is None


async def test_vec_close_is_safe_when_unconnected() -> None:
    vec = VectorStore.from_env()
    await vec.close()
