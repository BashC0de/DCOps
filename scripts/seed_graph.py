"""Seed the Neo4j knowledge graph with sites, halls, racks, devices, and edges.

Idempotent: re-running won't duplicate nodes or relationships (uses MERGE).

Schema seeded (see ARCHITECTURE.md § Knowledge graph schema):
    Nodes:         Site, Hall, Rack, Device
    Containment:   (Hall)-[:LOCATED_IN]->(Site)
                   (Rack)-[:LOCATED_IN]->(Hall)
                   (Device)-[:MOUNTED_IN]->(Rack)
    Dependencies:  (Server)-[:POWERED_BY]->(PDU)
                   (Server)-[:DEPENDS_ON]->(Switch)
                   (GPU)-[:DEPENDS_ON]->(Server)
                   (Rack)-[:COOLED_BY]->(CRAC)
                   (CRAC)-[:COOLS]->(Hall)               # legacy, kept

These dependency edges drive Forensic's 2-hop subgraph queries
(`apps.agents.shared.kg_client.dependency_subgraph`).

Run via `make seed` or directly:
    python scripts/seed_graph.py
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Allow running this script directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402
from apps.physics.entities import CRACUnit, DataHall, GPU, PDU, Server, Switch  # noqa: E402
from apps.simulator.devices import build_halls  # noqa: E402
from apps.simulator.sites import SITES  # noqa: E402

log = get_logger("seed_graph")


# ---------------------------------------------------------------------------
# Cypher statement builders. Pure functions — unit-tested in tests/unit.
# ---------------------------------------------------------------------------


def _site_statements(site_id: str, region: str, timezone_: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "MERGE (s:Site {id: $id}) SET s.region = $region, s.timezone = $tz",
            {"id": site_id, "region": region, "tz": timezone_},
        )
    ]


def _hall_statements(hall: DataHall) -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "MERGE (h:Hall {id: $id}) SET h.capacity_kw = $cap "
            "WITH h MATCH (s:Site {id: $site}) MERGE (h)-[:LOCATED_IN]->(s)",
            {"id": hall.id, "cap": hall.capacity_kw, "site": hall.site_id},
        )
    ]


def _rack_statements(hall_id: str, rack_id: str, position: tuple[int, int]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "MERGE (r:Rack {id: $id}) SET r.position = $pos "
            "WITH r MATCH (h:Hall {id: $hall}) MERGE (r)-[:LOCATED_IN]->(h)",
            {"id": rack_id, "pos": list(position), "hall": hall_id},
        )
    ]


def _device_node_statements(
    device_id: str, rack_id: str, type_: str, model: str, vendor: str
) -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "MERGE (d:Device {id: $id}) "
            "SET d.type = $type, d.model = $model, d.vendor = $vendor "
            "WITH d MATCH (r:Rack {id: $rack}) MERGE (d)-[:MOUNTED_IN]->(r)",
            {"id": device_id, "type": type_, "model": model, "vendor": vendor, "rack": rack_id},
        )
    ]


def _crac_node_and_hall_link(crac_id: str, model: str, vendor: str, hall_id: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "MERGE (d:Device {id: $id}) "
            "SET d.type = 'crac', d.model = $model, d.vendor = $vendor "
            "WITH d MATCH (h:Hall {id: $hall}) MERGE (d)-[:COOLS]->(h)",
            {"id": crac_id, "model": model, "vendor": vendor, "hall": hall_id},
        )
    ]


def _powered_by(server_id: str, pdu_id: str) -> tuple[str, dict[str, Any]]:
    return (
        "MATCH (s:Device {id: $server}), (p:Device {id: $pdu}) "
        "MERGE (s)-[:POWERED_BY]->(p)",
        {"server": server_id, "pdu": pdu_id},
    )


def _depends_on(downstream_id: str, upstream_id: str) -> tuple[str, dict[str, Any]]:
    """downstream DEPENDS_ON upstream (server→switch, gpu→server)."""
    return (
        "MATCH (a:Device {id: $a}), (b:Device {id: $b}) "
        "MERGE (a)-[:DEPENDS_ON]->(b)",
        {"a": downstream_id, "b": upstream_id},
    )


def _cooled_by(rack_id: str, crac_id: str) -> tuple[str, dict[str, Any]]:
    return (
        "MATCH (r:Rack {id: $rack}), (c:Device {id: $crac}) "
        "MERGE (r)-[:COOLED_BY]->(c)",
        {"rack": rack_id, "crac": crac_id},
    )


# ---------------------------------------------------------------------------
# Per-hall plan: deterministic list of (cypher, params) tuples.
# ---------------------------------------------------------------------------


def plan_for_site(site_id: str, region: str, timezone_: str) -> list[tuple[str, dict[str, Any]]]:
    """Build the full sequence of statements to seed one site.

    Pure function — no Neo4j needed. Drives the runner below.
    """
    stmts: list[tuple[str, dict[str, Any]]] = []
    stmts.extend(_site_statements(site_id, region, timezone_))

    halls = build_halls(_site_spec(site_id))
    for hall in halls:
        stmts.extend(_hall_statements(hall))

        crac_ids = [c.id for c in hall.crac_units]
        for crac in hall.crac_units:
            stmts.extend(_crac_node_and_hall_link(crac.id, crac.model, crac.vendor, hall.id))

        for rack in hall.racks:
            stmts.extend(_rack_statements(hall.id, rack.id, rack.position))

            # Index devices by type so we can resolve PDU / Switch IDs for edges.
            servers: list[Server] = []
            switches: list[Switch] = []
            pdus: list[PDU] = []
            gpus: list[GPU] = []
            for device in rack.devices:
                stmts.extend(
                    _device_node_statements(device.id, rack.id, device.type, device.model, device.vendor)
                )
                if isinstance(device, Server):
                    servers.append(device)
                elif isinstance(device, Switch):
                    switches.append(device)
                elif isinstance(device, PDU):
                    pdus.append(device)
                elif isinstance(device, GPU):
                    gpus.append(device)

            # Rack → CRAC (the hall has one CRAC; all racks COOLED_BY it).
            for crac_id in crac_ids:
                stmts.append(_cooled_by(rack.id, crac_id))

            # Server → PDU (PDU.powered_device_ids is the source of truth).
            for pdu in pdus:
                for srv_id in pdu.powered_device_ids:
                    stmts.append(_powered_by(srv_id, pdu.id))

            # Server → Switch (every server in the rack depends on the ToR).
            for switch in switches:
                for srv in servers:
                    stmts.append(_depends_on(srv.id, switch.id))

            # GPU → Server (parent_server_id).
            for gpu in gpus:
                if gpu.parent_server_id:
                    stmts.append(_depends_on(gpu.id, gpu.parent_server_id))

    return stmts


def plan_for_all_sites() -> Iterable[tuple[str, list[tuple[str, dict[str, Any]]]]]:
    """Yield (site_id, statements) per site. Streaming so memory stays bounded."""
    for site in SITES:
        yield site.id, plan_for_site(site.id, site.region, site.timezone)


def _site_spec(site_id: str) -> Any:
    """Look up the dataclass spec for `site_id`. Raises if unknown."""
    for s in SITES:
        if s.id == site_id:
            return s
    raise LookupError(f"Unknown site: {site_id}")


# ---------------------------------------------------------------------------
# Runner — applies the plan against a real Neo4j driver.
# ---------------------------------------------------------------------------


def run_schema(driver: Any) -> None:
    """Apply constraints + indexes from seed_schema.cypher."""
    schema_path = (
        Path(__file__).resolve().parents[1] / "infra" / "neo4j" / "import" / "seed_schema.cypher"
    )
    schema = schema_path.read_text()
    with driver.session() as session:
        for statement in schema.split(";"):
            stmt = statement.strip()
            if stmt and not stmt.startswith("//"):
                session.run(stmt)
    log.info("seed_graph.schema_applied")


def apply_plan(driver: Any) -> dict[str, int]:
    """Execute the full plan for every site. Returns stmt counts per site."""
    counts: dict[str, int] = {}
    with driver.session() as session:
        for site_id, plan in plan_for_all_sites():
            for cypher, params in plan:
                session.run(cypher, **params)
            counts[site_id] = len(plan)
            log.info("seed_graph.site_loaded", site=site_id, statements=len(plan))
    return counts


def main() -> None:
    configure_logging()
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "changeme_neo4j")
    log.info("seed_graph.connect", uri=uri)
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        run_schema(driver)
        counts = apply_plan(driver)
        log.info("seed_graph.done", total_statements=sum(counts.values()))
    finally:
        driver.close()


if __name__ == "__main__":
    main()


__all__ = ["plan_for_site", "plan_for_all_sites", "apply_plan", "run_schema"]
