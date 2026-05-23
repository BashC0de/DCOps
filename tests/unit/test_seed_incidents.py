"""Tests for the past-incidents Chroma seeder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from scripts._incidents_corpus import CORPUS, by_kind
from scripts.seed_incidents import seed, to_chroma_payload

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


# --- corpus shape --------------------------------------------------------------

def test_corpus_is_nonempty() -> None:
    assert len(CORPUS) >= 15


def test_corpus_ids_are_unique() -> None:
    ids = [p.id for p in CORPUS]
    assert len(ids) == len(set(ids))


def test_corpus_covers_main_failure_kinds() -> None:
    kinds = set(by_kind().keys())
    # Subset of kinds the rule layer + agents care about.
    expected_subset = {
        "gpu_ecc_drift",
        "gpu_fatal_xid",
        "gpu_thermal",
        "psu_efficiency_drift",
        "psu_fail",
        "crac_fail",
        "thermal_cascade",
        "disk_smart_drift",
        "switch_port_flap",
        "nic_packet_loss",
        "pdu_overload",
    }
    missing = expected_subset - kinds
    assert not missing, f"corpus missing kinds: {missing}"


def test_every_entry_has_root_cause_and_resolution() -> None:
    for p in CORPUS:
        assert p.symptoms.strip()
        assert p.root_cause.strip()
        assert p.resolution.strip()
        assert p.severity in {"info", "warn", "error", "critical"}


# --- payload mapping -----------------------------------------------------------

def test_to_chroma_payload_aligns_arrays() -> None:
    payload = to_chroma_payload(CORPUS)
    assert len(payload["ids"]) == len(payload["documents"]) == len(payload["metadatas"])
    assert len(payload["ids"]) == len(CORPUS)


def test_to_chroma_payload_documents_are_symptoms() -> None:
    payload = to_chroma_payload(CORPUS)
    assert payload["documents"][0] == CORPUS[0].symptoms


def test_to_chroma_payload_metadata_contains_required_fields() -> None:
    payload = to_chroma_payload(CORPUS)
    meta0 = payload["metadatas"][0]
    assert set(meta0.keys()) == {"root_cause", "resolution", "severity", "kind"}


# --- seeder ------------------------------------------------------------------

def test_seed_upserts_corpus_into_collection() -> None:
    client = _FakeClient()
    n = seed(client, collection_name="dcops_incidents_test")
    assert n == len(CORPUS)
    assert len(client.collection.upserts) == 1
    upserted = client.collection.upserts[0]
    assert upserted["ids"][0] == CORPUS[0].id
    assert upserted["documents"][0] == CORPUS[0].symptoms
