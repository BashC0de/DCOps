"""Tests for the Optimizer's OR-Tools CP-SAT solver."""

from __future__ import annotations

import pytest

from apps.agents.optimizer.solver import (
    Move,
    Rack,
    SolverInput,
    Workload,
    estimate_impact,
    solve,
)

pytestmark = pytest.mark.unit


def _wl(id_: str, rack: str, power: float, tier: str = "compute") -> Workload:
    return Workload(
        id=id_,
        current_rack_id=rack,
        power_w=power,
        thermal_load_kw=power * 0.9 / 1000.0,
        tier=tier,
    )


def _rack(id_: str, *, power_cap: float = 10_000, thermal_cap: float = 8.0, inlet: float = 22.0) -> Rack:
    return Rack(
        id=id_,
        pdu_capacity_w=power_cap,
        thermal_headroom_kw=thermal_cap,
        current_inlet_c=inlet,
    )


def test_solver_empty_input_returns_noop() -> None:
    out = solve(SolverInput(incident_rack_id="r-incident", workloads=(), racks=()))
    assert out.feasible
    assert out.is_noop()


def test_solver_finds_migration_off_hot_rack() -> None:
    workloads = (
        _wl("wl-1", "rack-hot", 1500.0),
        _wl("wl-2", "rack-hot", 1200.0),
        _wl("wl-3", "rack-hot", 800.0),
    )
    racks = (
        _rack("rack-hot",  power_cap=200,  thermal_cap=0.2, inlet=30.0),  # almost full + hot
        _rack("rack-cool-a", power_cap=15_000, thermal_cap=12.0, inlet=22.0),
        _rack("rack-cool-b", power_cap=15_000, thermal_cap=12.0, inlet=21.5),
    )
    out = solve(SolverInput(
        incident_rack_id="rack-hot",
        workloads=workloads,
        racks=racks,
        time_limit_s=5.0,
    ))
    assert out.feasible
    assert out.solve_status in ("OPTIMAL", "FEASIBLE")
    # All 3 workloads should land off the hot rack.
    assert len(out.moves) == 3
    assert all(m.from_rack_id == "rack-hot" for m in out.moves)
    assert all(m.to_rack_id != "rack-hot" for m in out.moves)


def test_solver_respects_power_caps() -> None:
    """A workload that exceeds every alternative rack's power cap stays put."""
    workloads = (_wl("wl-1", "rack-A", 9_000.0),)
    racks = (
        _rack("rack-A", power_cap=10_000, thermal_cap=10.0, inlet=25.0),
        _rack("rack-B", power_cap=2_000, thermal_cap=10.0, inlet=22.0),  # too small
    )
    out = solve(SolverInput(
        incident_rack_id="rack-A",
        workloads=workloads,
        racks=racks,
    ))
    assert out.feasible
    # rack-B can't take it; workload either stays on A or solver returns no-move.
    # Either way, no move to rack-B.
    assert all(m.to_rack_id != "rack-B" for m in out.moves)


def test_solver_anti_affinity_spreads_same_tier() -> None:
    """Three same-tier workloads + three racks → expect ≤1 per rack."""
    workloads = (
        _wl("wl-1", "rack-A", 500.0, tier="ha-group-1"),
        _wl("wl-2", "rack-A", 500.0, tier="ha-group-1"),
        _wl("wl-3", "rack-A", 500.0, tier="ha-group-1"),
    )
    racks = (
        _rack("rack-A", power_cap=8_000, thermal_cap=8.0, inlet=30.0),
        _rack("rack-B", power_cap=8_000, thermal_cap=8.0, inlet=22.0),
        _rack("rack-C", power_cap=8_000, thermal_cap=8.0, inlet=22.0),
    )
    out = solve(SolverInput(
        incident_rack_id="rack-A",
        workloads=workloads,
        racks=racks,
    ))
    assert out.feasible
    # The 3 same-tier workloads must spread; each rack holds at most 1.
    placement = {m.workload_id: m.to_rack_id for m in out.moves}
    # Workloads that didn't move stayed on rack-A.
    for w in workloads:
        placement.setdefault(w.id, w.current_rack_id)
    by_rack: dict[str, int] = {}
    for rack in placement.values():
        by_rack[rack] = by_rack.get(rack, 0) + 1
    assert max(by_rack.values()) <= 1, f"anti-affinity violated: {by_rack}"


def test_solver_no_eligible_targets_returns_infeasible() -> None:
    racks = (_rack("rack-A", power_cap=0, thermal_cap=0, inlet=30.0),)
    workloads = (_wl("wl-1", "rack-A", 1000.0),)
    out = solve(SolverInput(
        incident_rack_id="rack-A",
        workloads=workloads,
        racks=racks,
    ))
    assert not out.feasible
    assert out.solve_status == "NO_ELIGIBLE_TARGETS"


def test_estimate_impact_aggregates() -> None:
    moves = [
        Move("wl-1", "a", "b", 1000.0, 0.9),
        Move("wl-2", "a", "c", 500.0, 0.45),
    ]
    impact = estimate_impact(moves)
    assert impact["power_redistributed_w"] == pytest.approx(1500.0)
    assert impact["thermal_redistributed_kw"] == pytest.approx(1.35)
    assert impact["n_workload_migrations"] == 2.0
