"""Tests for apps/agents/shared/quality/semantic_cache.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.agents.shared.quality.semantic_cache import SemanticCache, _prompt_id

pytestmark = pytest.mark.unit


@dataclass
class _FakeCollection:
    """In-memory stand-in for a Chroma collection."""

    upserts: list[dict[str, Any]] = field(default_factory=list)
    query_result: dict[str, Any] = field(default_factory=lambda: {"distances": [[]], "metadatas": [[]]})

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self.upserts.append({"ids": ids, "documents": documents, "metadatas": metadatas})

    def query(self, *, query_texts: list[str], n_results: int) -> dict[str, Any]:
        _ = (query_texts, n_results)
        return self.query_result


@dataclass
class _FakeClient:
    collection: _FakeCollection

    def get_or_create_collection(self, **_: Any) -> _FakeCollection:
        return self.collection


async def test_disabled_without_client() -> None:
    cache = SemanticCache(client=None)
    assert cache.enabled is False
    assert await cache.get("anything") is None
    await cache.put("anything", "response")  # must not raise


async def test_put_stores_prompt_as_document_and_response_in_metadata() -> None:
    coll = _FakeCollection()
    cache = SemanticCache(client=_FakeClient(coll))
    await cache.put("how hot is rack 7?", "answer text", metadata={"agent": "operator"})

    assert len(coll.upserts) == 1
    write = coll.upserts[0]
    assert write["documents"] == ["how hot is rack 7?"]
    assert write["metadatas"][0]["response"] == "answer text"
    assert write["metadatas"][0]["agent"] == "operator"
    assert write["ids"] == [_prompt_id("how hot is rack 7?")]


async def test_get_returns_cached_response_above_threshold() -> None:
    coll = _FakeCollection()
    coll.query_result = {
        "distances": [[0.02]],  # similarity = 0.98 > 0.97
        "metadatas": [[{"response": "cached answer"}]],
    }
    cache = SemanticCache(client=_FakeClient(coll))
    assert await cache.get("question") == "cached answer"


async def test_get_misses_below_threshold() -> None:
    coll = _FakeCollection()
    coll.query_result = {
        "distances": [[0.5]],  # similarity = 0.5 < 0.97
        "metadatas": [[{"response": "stale"}]],
    }
    cache = SemanticCache(client=_FakeClient(coll))
    assert await cache.get("question") is None


async def test_get_misses_on_empty_results() -> None:
    coll = _FakeCollection()
    coll.query_result = {"distances": [[]], "metadatas": [[]]}
    cache = SemanticCache(client=_FakeClient(coll))
    assert await cache.get("question") is None


async def test_get_misses_when_metadata_lacks_response() -> None:
    coll = _FakeCollection()
    coll.query_result = {
        "distances": [[0.01]],
        "metadatas": [[{"agent": "operator"}]],  # no `response` key
    }
    cache = SemanticCache(client=_FakeClient(coll))
    assert await cache.get("question") is None
