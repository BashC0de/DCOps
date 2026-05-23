"""Tests for the Cypher plan builders in scripts/seed_graph.py.

We don't connect to Neo4j; we assert the plan is structurally correct:
right node types, right edges in the right direction, no duplicates.
"""

from __future__ import annotations

from collections import Counter

import pytest

from scripts.seed_graph import plan_for_site

pytestmark = pytest.mark.unit


def _stmts(site_id: str = "frankfurt") -> list[tuple[str, dict]]:
    # The site's region/timezone come from SITES in apps.simulator.sites.
    from apps.simulator.sites import get_site
    s = get_site(site_id)
    return plan_for_site(s.id, s.region, s.timezone)


def test_plan_starts_with_site_node() -> None:
    plan = _stmts("frankfurt")
    first_cypher, first_params = plan[0]
    assert "MERGE (s:Site {id: $id})" in first_cypher
    assert first_params["id"] == "frankfurt"


def test_plan_includes_hall_locations() -> None:
    plan = _stmts("frankfurt")
    hall_stmts = [c for c, _ in plan if "MERGE (h:Hall" in c]
    assert hall_stmts, "expected at least one hall MERGE"
    assert all("LOCATED_IN" in c for c in hall_stmts)


def test_plan_includes_rack_locations() -> None:
    plan = _stmts("frankfurt")
    rack_stmts = [c for c, _ in plan if "MERGE (r:Rack" in c]
    assert rack_stmts, "expected rack statements"
    assert all("LOCATED_IN" in c for c in rack_stmts)


def test_plan_includes_dependency_edges() -> None:
    """The whole point of Week 5 — DEPENDS_ON, POWERED_BY, COOLED_BY all show up."""
    plan = _stmts("frankfurt")
    counts = Counter()
    for c, _ in plan:
        if ":POWERED_BY" in c:
            counts["powered_by"] += 1
        if ":DEPENDS_ON" in c:
            counts["depends_on"] += 1
        if ":COOLED_BY" in c:
            counts["cooled_by"] += 1
    assert counts["powered_by"] > 0, "missing POWERED_BY edges (server → PDU)"
    assert counts["depends_on"] > 0, "missing DEPENDS_ON edges (server → switch / gpu → server)"
    assert counts["cooled_by"] > 0, "missing COOLED_BY edges (rack → CRAC)"


def test_plan_powered_by_uses_real_pdu_targets() -> None:
    """Every POWERED_BY edge must point at a PDU device id."""
    plan = _stmts("frankfurt")
    for cypher, params in plan:
        if ":POWERED_BY" in cypher:
            pdu = params.get("pdu")
            assert isinstance(pdu, str)
            assert "-pdu-" in pdu, f"unexpected PDU id: {pdu}"


def test_plan_depends_on_includes_switch_and_gpu_links() -> None:
    plan = _stmts("frankfurt")
    has_server_to_switch = False
    has_gpu_to_server = False
    for cypher, params in plan:
        if ":DEPENDS_ON" not in cypher:
            continue
        upstream = params.get("b", "")
        downstream = params.get("a", "")
        if "-tor" in upstream:
            has_server_to_switch = True
        if "-gpu" in downstream:
            has_gpu_to_server = True
    assert has_server_to_switch, "expected at least one server→switch DEPENDS_ON"
    assert has_gpu_to_server, "expected at least one GPU→server DEPENDS_ON"


def test_plan_cooled_by_targets_crac() -> None:
    plan = _stmts("frankfurt")
    for cypher, params in plan:
        if ":COOLED_BY" in cypher:
            crac = params.get("crac", "")
            assert "crac" in crac, f"COOLED_BY must target a CRAC, got {crac}"


def test_plan_is_nontrivial() -> None:
    """Sanity: the seed plan for one site should be well over 100 statements."""
    plan = _stmts("frankfurt")
    assert len(plan) > 100
