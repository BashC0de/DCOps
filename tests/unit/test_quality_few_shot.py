"""Tests for apps/agents/shared/quality/few_shot.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from apps.agents.shared.quality.few_shot import FewShotRetriever

pytestmark = pytest.mark.unit


@dataclass
class _FakeCollection:
    result: dict[str, Any]

    def query(self, *, query_texts: list[str], n_results: int) -> dict[str, Any]:
        _ = (query_texts, n_results)
        return self.result


@dataclass
class _FakeClient:
    collection: _FakeCollection

    def get_or_create_collection(self, **_: Any) -> _FakeCollection:
        return self.collection


async def test_disabled_without_client_returns_empty() -> None:
    retriever = FewShotRetriever(client=None)
    assert retriever.enabled is False
    assert await retriever.retrieve("symptoms") == []


async def test_retrieve_returns_documents_metadata_distances() -> None:
    coll = _FakeCollection(
        result={
            "documents": [["sym a", "sym b"]],
            "metadatas": [[{"root_cause": "psu", "resolution": "swap"}, {"root_cause": "fan"}]],
            "distances": [[0.1, 0.2]],
        }
    )
    retriever = FewShotRetriever(client=_FakeClient(coll))

    out = await retriever.retrieve("rack hot", k=2)
    assert len(out) == 2
    assert out[0]["document"] == "sym a"
    assert out[0]["metadata"]["root_cause"] == "psu"
    assert out[0]["distance"] == pytest.approx(0.1)


def test_format_as_examples_renders_block() -> None:
    examples = [
        {
            "document": "fans spiking on rack 4",
            "metadata": {"root_cause": "CRAC supply drift", "resolution": "increased fan speed"},
            "distance": 0.1,
        }
    ]
    block = FewShotRetriever.format_as_examples(examples)
    assert "EXAMPLES" in block
    assert "fans spiking on rack 4" in block
    assert "CRAC supply drift" in block
    assert "increased fan speed" in block


def test_format_as_examples_empty_returns_empty_string() -> None:
    assert FewShotRetriever.format_as_examples([]) == ""
