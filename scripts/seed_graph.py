"""Seed the Neo4j knowledge graph with sites, halls, racks, devices.

Idempotent: re-running won't duplicate nodes (uses MERGE).

Run via `make seed` or directly:
    python scripts/seed_graph.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running this script directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neo4j import GraphDatabase  # noqa: E402

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402
from apps.simulator.devices import build_halls  # noqa: E402
from apps.simulator.sites import SITES  # noqa: E402

log = get_logger("seed_graph")


def run_schema(driver: GraphDatabase.driver) -> None:
    """Apply constraints + indexes from seed_schema.cypher."""
    schema = (Path(__file__).resolve().parents[1] / "infra" / "neo4j" / "import" / "seed_schema.cypher").read_text()
    with driver.session() as session:
        for statement in schema.split(";"):
            stmt = statement.strip()
            if stmt and not stmt.startswith("//"):
                session.run(stmt)
    log.info("seed_graph.schema_applied")


def seed_data(driver: GraphDatabase.driver) -> None:
    """Walk every site spec and write nodes + relationships."""
    with driver.session() as session:
        for site in SITES:
            session.run(
                "MERGE (s:Site {id: $id}) SET s.region = $region, s.timezone = $tz",
                id=site.id, region=site.region, tz=site.timezone,
            )
            halls = build_halls(site)
            for hall in halls:
                session.run(
                    "MERGE (h:Hall {id: $id}) SET h.capacity_kw = $cap "
                    "WITH h MATCH (s:Site {id: $site}) MERGE (h)-[:LOCATED_IN]->(s)",
                    id=hall.id, cap=hall.capacity_kw, site=hall.site_id,
                )
                for rack in hall.racks:
                    session.run(
                        "MERGE (r:Rack {id: $id}) SET r.position = $pos, r.capacity_u = $cap "
                        "WITH r MATCH (h:Hall {id: $hall}) MERGE (r)-[:LOCATED_IN]->(h)",
                        id=rack.id, pos=list(rack.position), cap=rack.capacity_u, hall=rack.hall_id,
                    )
                    for device in rack.devices:
                        session.run(
                            "MERGE (d:Device {id: $id}) "
                            "SET d.type = $type, d.model = $model, d.vendor = $vendor "
                            "WITH d MATCH (r:Rack {id: $rack}) MERGE (d)-[:MOUNTED_IN]->(r)",
                            id=device.id, type=device.type, model=device.model,
                            vendor=device.vendor, rack=rack.id,
                        )
                for crac in hall.crac_units:
                    session.run(
                        "MERGE (d:Device {id: $id}) "
                        "SET d.type = 'crac', d.model = $model, d.vendor = $vendor "
                        "WITH d MATCH (h:Hall {id: $hall}) MERGE (d)-[:COOLS]->(h)",
                        id=crac.id, model=crac.model, vendor=crac.vendor, hall=hall.id,
                    )
            log.info("seed_graph.site_loaded", site=site.id)


def main() -> None:
    configure_logging()
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "changeme_neo4j")
    log.info("seed_graph.connect", uri=uri)
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        run_schema(driver)
        seed_data(driver)
        log.info("seed_graph.done")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
