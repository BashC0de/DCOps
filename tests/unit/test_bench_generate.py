"""Tests for the deterministic scenario generator."""

from __future__ import annotations

import pytest

from benchmarks.generate import SITES, categorise, categorise_many, generate

pytestmark = pytest.mark.unit


def test_generate_reaches_target_count() -> None:
    scenarios = generate(target=200)
    assert len(scenarios) == 200


def test_generate_is_deterministic() -> None:
    a = generate(target=50, seed=7)
    b = generate(target=50, seed=7)
    assert [s.name for s in a] == [s.name for s in b]


def test_generate_includes_curated_scenarios() -> None:
    # Curated scenarios from disk should come first.
    scenarios = generate(target=200)
    curated = [s.name for s in scenarios if not s.name.startswith("gen_")]
    assert "gpu_ecc_failure" in curated
    assert "crac_failure" in curated


def test_generate_covers_every_site() -> None:
    scenarios = generate(target=200)
    sites_seen = {site for site in SITES if any(site in s.name for s in scenarios)}
    assert sites_seen == set(SITES)


def test_generate_includes_federated_scenarios() -> None:
    scenarios = generate(target=200)
    federated = [s for s in scenarios if s.name.startswith("gen_federated_")]
    assert federated, "expected at least one federated scenario"


def test_categorise_buckets_correctly() -> None:
    assert categorise("gen_gpu_gpu_ecc_runaway_frankfurt_0") == "gpu"
    assert categorise("gen_cooling_crac_fail_singapore_0") == "cooling"
    assert categorise("gen_federated_gpu_ecc_frankfurt") == "federated"
    assert categorise("gpu_ecc_failure") == "gpu"
    assert categorise("crac_failure") == "cooling"
    assert categorise("switch_cascade") == "network"


def test_categorise_many_groups() -> None:
    scenarios = generate(target=50)
    grouped = categorise_many(scenarios)
    # At least gpu + cooling + federated should be present.
    assert "gpu" in grouped
    assert sum(len(v) for v in grouped.values()) == len(scenarios)
