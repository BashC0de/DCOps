"""Tests for the runbooks corpus + Chroma seeder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from scripts._runbooks_corpus import CORPUS, by_category
from scripts.seed_runbooks import seed, to_chroma_payload

pytestmark = pytest.mark.unit


@dataclass
class _FakeCollection:
    upserts: list[dict[str, Any]] = field(default_factory=list)

    def upsert(self, **kwargs: Any) -> None:
        self.upserts.append(kwargs)


@dataclass
class _FakeClient:
    collection: _FakeCollection = field(default_factory=_FakeCollection)

    def get_or_create_collection(self, *, name: str) -> _FakeCollection:
        _ = name
        return self.collection


def test_corpus_is_nonempty_and_unique() -> None:
    assert len(CORPUS) >= 15
    assert len({r.id for r in CORPUS}) == len(CORPUS)


def test_corpus_covers_main_categories() -> None:
    cats = set(by_category().keys())
    assert {"thermal", "power", "gpu", "storage", "network", "fleet"} <= cats


def test_every_runbook_has_required_fields() -> None:
    for r in CORPUS:
        assert r.question.strip()
        assert r.sql_template.strip()
        # Refuse to ship runbook SQL that mutates state.
        upper = r.sql_template.upper()
        for tok in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", " INTO "):
            assert tok not in " " + upper + " ", f"runbook {r.id} uses forbidden token {tok!r}"


def test_to_chroma_payload_aligns_arrays() -> None:
    p = to_chroma_payload(CORPUS)
    assert len(p["ids"]) == len(p["documents"]) == len(p["metadatas"]) == len(CORPUS)


def test_to_chroma_payload_documents_are_questions() -> None:
    p = to_chroma_payload(CORPUS)
    assert p["documents"][0] == CORPUS[0].question


def test_to_chroma_payload_metadata_keys() -> None:
    p = to_chroma_payload(CORPUS)
    meta0 = p["metadatas"][0]
    assert set(meta0.keys()) == {"sql_template", "metrics", "category", "notes"}


def test_seed_upserts_corpus() -> None:
    client = _FakeClient()
    n = seed(client, collection_name="dcops_runbooks_test")
    assert n == len(CORPUS)
    assert len(client.collection.upserts) == 1
    upserted = client.collection.upserts[0]
    assert upserted["ids"][0] == CORPUS[0].id
