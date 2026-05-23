"""OR-Tools CP-SAT solver for workload-to-rack placement.

Given a set of workloads with power/thermal demand and a set of racks
with power capacity + thermal headroom, find a placement that minimises
the worst-case post-move thermal stress while honoring:
    - Per-rack power capacity (sum of placed workload watts ≤ rack PDU cap)
    - Per-rack thermal headroom (post-move inlet remains ≤ target)
    - Anti-affinity: workloads in the same `tier` can't all land on one rack

Pure function. The agent main loop wraps this with bus + persistence.

Time budget: hard cap from `OPTIMIZER_SOLVER_TIME_LIMIT_SEC` env (default 10s).
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Workload:
    """A unit we want to place. Could be one server's load, a service, etc."""

    id: str
    current_rack_id: str
    power_w: float                 # estimated draw
    thermal_load_kw: float         # heat to dissipate (~power, but separately tunable)
    tier: str = "default"          # affinity group; same-tier workloads spread


@dataclass(frozen=True)
class Rack:
    """A placement target."""

    id: str
    pdu_capacity_w: float          # remaining headroom across both PDUs
    thermal_headroom_kw: float     # how much extra heat the rack can take
    current_inlet_c: float         # for ranking / objective
    target_inlet_c: float = 27.0   # don't exceed this


@dataclass(frozen=True)
class SolverInput:
    incident_rack_id: str
    workloads: tuple[Workload, ...]
    racks: tuple[Rack, ...]
    time_limit_s: float | None = None


@dataclass(frozen=True)
class Move:
    workload_id: str
    from_rack_id: str
    to_rack_id: str
    expected_power_w: float
    expected_thermal_kw: float


@dataclass
class SolverOutput:
    feasible: bool
    moves: list[Move] = field(default_factory=list)
    objective_value: float = 0.0
    solve_status: str = "UNKNOWN"
    notes: str = ""

    def is_noop(self) -> bool:
        return not self.moves


_DEFAULT_TIME_LIMIT_S = float(os.getenv("OPTIMIZER_SOLVER_TIME_LIMIT_SEC", "10"))


def solve(inp: SolverInput) -> SolverOutput:
    """Solve the placement problem. Returns SolverOutput with chosen moves."""
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        return SolverOutput(
            feasible=False,
            solve_status="UNAVAILABLE",
            notes=f"ortools missing: {exc}",
        )

    workloads = list(inp.workloads)
    racks = list(inp.racks)
    if not workloads or not racks:
        return SolverOutput(feasible=True, solve_status="EMPTY", notes="no work to do")

    # Sanity: shrink the search by excluding racks with no room at all.
    racks_eligible = [
        r for r in racks
        if r.pdu_capacity_w > 0 and r.thermal_headroom_kw > 0
    ]
    if not racks_eligible:
        return SolverOutput(
            feasible=False,
            solve_status="NO_ELIGIBLE_TARGETS",
            notes="no rack with both power + thermal headroom",
        )

    model = cp_model.CpModel()

    rack_ids = [r.id for r in racks_eligible]
    rack_by_id = {r.id: r for r in racks_eligible}

    # x[w][r] = 1 iff workload w is placed on rack r.
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    for w in workloads:
        candidates = [r_id for r_id in rack_ids]
        # Every workload must be assigned to exactly one rack.
        vars_for_w = []
        for r_id in candidates:
            v = model.NewBoolVar(f"x_{w.id}_{r_id}")
            x[(w.id, r_id)] = v
            vars_for_w.append(v)
        model.AddExactlyOne(vars_for_w)

    # Power capacity per rack (in milliwatts to keep ints).
    for r in racks_eligible:
        cap_mw = int(r.pdu_capacity_w * 1000)
        model.Add(
            sum(
                int(w.power_w * 1000) * x[(w.id, r.id)]
                for w in workloads
            ) <= cap_mw
        )

    # Thermal capacity per rack (in watts to keep ints).
    for r in racks_eligible:
        cap_w = int(r.thermal_headroom_kw * 1000)  # kW → W
        model.Add(
            sum(
                int(w.thermal_load_kw * 1000) * x[(w.id, r.id)]
                for w in workloads
            ) <= cap_w
        )

    # Anti-affinity: spread workloads sharing an EXPLICIT redundancy group
    # ("ha-group-X" etc.) across racks. Generic tiers ("default", "compute",
    # "gpu", "switch") describe workload kind, not redundancy, so they don't
    # impose spreading — otherwise a small cluster with 3 servers + 3 racks
    # would force one workload per rack and bind the solver.
    NON_AFFINITY_TIERS = {"default", "compute", "gpu", "switch"}
    by_tier: dict[str, list[Workload]] = defaultdict(list)
    for w in workloads:
        if w.tier in NON_AFFINITY_TIERS:
            continue
        by_tier[w.tier].append(w)
    for tier, members in by_tier.items():
        n = len(members)
        if n <= 1:
            continue
        per_rack_cap = max(1, (n + len(racks_eligible) - 1) // len(racks_eligible))
        for r in racks_eligible:
            model.Add(
                sum(x[(w.id, r.id)] for w in members) <= per_rack_cap
            )

    # Objective: minimise post-move inlet temperature stress.
    # Approximation: penalise placing workload back on the incident rack;
    # and prefer cooler racks for high-thermal workloads.
    # Cost = sum_w sum_r x[w,r] * cost(w, r)
    # cost(w, r) = thermal_load_kw_w * (current_inlet_c_r ** 2)
    #   plus a big penalty if r is the incident rack.
    incident_penalty = 1_000_000
    cost_terms: list[cp_model.IntVar | int] = []
    for w in workloads:
        for r in racks_eligible:
            cost = int(round(w.thermal_load_kw * (r.current_inlet_c ** 2)))
            if r.id == inp.incident_rack_id:
                cost += incident_penalty
            cost_terms.append(cost * x[(w.id, r.id)])
    model.Minimize(sum(cost_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = inp.time_limit_s or _DEFAULT_TIME_LIMIT_S
    # Single worker — keeps deterministic + low CPU on the laptop budget.
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)

    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolverOutput(
            feasible=False,
            solve_status=status_name,
            notes="solver could not find a feasible placement under constraints",
        )

    # Extract moves: only emit when the workload actually changed racks.
    moves: list[Move] = []
    for w in workloads:
        for r_id in rack_ids:
            if solver.Value(x[(w.id, r_id)]) == 1 and r_id != w.current_rack_id:
                moves.append(
                    Move(
                        workload_id=w.id,
                        from_rack_id=w.current_rack_id,
                        to_rack_id=r_id,
                        expected_power_w=w.power_w,
                        expected_thermal_kw=w.thermal_load_kw,
                    )
                )

    return SolverOutput(
        feasible=True,
        moves=moves,
        objective_value=float(solver.ObjectiveValue()),
        solve_status=status_name,
        notes=f"placed {len(workloads)} workloads, {len(moves)} migrations",
    )


def estimate_impact(moves: list[Move]) -> dict[str, float]:
    """Quick rollup for the Recommendation's `estimated_impact` field."""
    total_power_moved = sum(m.expected_power_w for m in moves)
    total_thermal_moved = sum(m.expected_thermal_kw for m in moves)
    return {
        "power_redistributed_w": total_power_moved,
        "thermal_redistributed_kw": total_thermal_moved,
        "n_workload_migrations": float(len(moves)),
    }


__all__ = [
    "Workload",
    "Rack",
    "SolverInput",
    "SolverOutput",
    "Move",
    "solve",
    "estimate_impact",
]
