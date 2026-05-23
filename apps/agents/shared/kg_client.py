"""Async Neo4j client wrapper.

Provides the queries the Forensic, Vision, Optimizer, and control-plane
agents need against the knowledge graph. Built on the official
`neo4j` async driver. Connection details come from env vars
(`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`).

Graceful degradation:
    Construct via `KnowledgeGraph.from_env()` — succeeds even when Neo4j
    is unreachable. `enabled` reflects whether the driver opened a
    connection. Methods that need the DB return safe defaults when
    disabled (empty list, None) and never raise, so an agent that lost
    Neo4j connectivity keeps operating in a degraded mode.

Schema reference: ARCHITECTURE.md § Knowledge graph schema.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from neo4j import AsyncDriver, AsyncSession

log = get_logger(__name__)


class KnowledgeGraph:
    """Lightweight async wrapper around `neo4j.AsyncDriver`."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str | None = None,
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver: AsyncDriver | None = None

    @classmethod
    def from_env(cls) -> KnowledgeGraph:
        return cls(
            uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "neo4j"),
            database=os.getenv("NEO4J_DATABASE") or None,
        )

    # --- lifecycle ------------------------------------------------------------

    async def connect(self) -> bool:
        """Open the driver. Returns True on success, False on failure.

        Idempotent — safe to call multiple times.
        """
        if self._driver is not None:
            return True
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError:
            log.warning("kg.import_failed", note="`neo4j` package not installed")
            return False
        try:
            self._driver = AsyncGraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
            await self._driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001
            log.warning("kg.connect_failed", uri=self._uri, error=str(exc))
            self._driver = None
            return False
        log.info("kg.connected", uri=self._uri)
        return True

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    @property
    def enabled(self) -> bool:
        return self._driver is not None

    def session(self) -> AsyncSession | None:
        """Acquire an async session. Returns None when disabled.

        Caller is responsible for closing the session (use `async with`).
        """
        if self._driver is None:
            return None
        return self._driver.session(database=self._database) if self._database else self._driver.session()

    # --- queries --------------------------------------------------------------

    async def validate_device_ids(self, device_ids: list[str]) -> list[str]:
        """Return device IDs NOT present as `(:Device {id})` nodes."""
        if self._driver is None or not device_ids:
            return []
        query = (
            "UNWIND $ids AS id "
            "OPTIONAL MATCH (d:Device {id: id}) "
            "WITH id, d WHERE d IS NULL "
            "RETURN id"
        )
        try:
            async with self._driver.session(database=self._database) if self._database else self._driver.session() as sess:
                result = await sess.run(query, ids=device_ids)
                return [record["id"] async for record in result]
        except Exception as exc:  # noqa: BLE001
            log.warning("kg.validate_devices_failed", error=str(exc))
            return []

    async def dependency_subgraph(
        self,
        device_id: str,
        hops: int = 2,
    ) -> list[dict[str, Any]]:
        """Return devices within `hops` of `device_id` via dependency edges.

        Edges considered: DEPENDS_ON, POWERED_BY, COOLED_BY (both directions).
        Each row is `{"id", "type", "model", "distance"}`.
        """
        if self._driver is None or hops < 1:
            return []
        hops = min(hops, 4)  # cap to keep latency bounded
        query = (
            "MATCH path = (:Device {id: $device_id})"
            f"-[:DEPENDS_ON|POWERED_BY|COOLED_BY*1..{hops}]-(neighbor:Device) "
            "RETURN DISTINCT "
            "  neighbor.id AS id, "
            "  neighbor.type AS type, "
            "  neighbor.model AS model, "
            "  length(path) AS distance "
            "ORDER BY distance ASC, id ASC "
            "LIMIT 50"
        )
        try:
            async with self._driver.session(database=self._database) if self._database else self._driver.session() as sess:
                result = await sess.run(query, device_id=device_id)
                return [dict(record) async for record in result]
        except Exception as exc:  # noqa: BLE001
            log.warning("kg.subgraph_failed", device_id=device_id, error=str(exc))
            return []

    async def validate_site_ids(self, site_ids: list[str]) -> list[str]:
        """Return site IDs NOT present as `(:Site {id})` nodes."""
        if self._driver is None or not site_ids:
            return []
        query = (
            "UNWIND $ids AS id "
            "OPTIONAL MATCH (s:Site {id: id}) "
            "WITH id, s WHERE s IS NULL "
            "RETURN id"
        )
        try:
            async with self._driver.session(database=self._database) if self._database else self._driver.session() as sess:
                result = await sess.run(query, ids=site_ids)
                return [record["id"] async for record in result]
        except Exception as exc:  # noqa: BLE001
            log.warning("kg.validate_sites_failed", error=str(exc))
            return []

    async def register_incident(
        self,
        *,
        incident_id: str,
        opened_at: str,
        severity: str,
        affected_device_ids: list[str],
    ) -> bool:
        """Create an `(:Incident)` node and link it to affected devices."""
        if self._driver is None:
            return False
        query = (
            "MERGE (i:Incident {id: $incident_id}) "
            "SET i.opened_at = datetime($opened_at), "
            "    i.severity = $severity "
            "WITH i "
            "UNWIND $devices AS dev_id "
            "MATCH (d:Device {id: dev_id}) "
            "MERGE (i)-[:AFFECTED]->(d)"
        )
        try:
            async with self._driver.session(database=self._database) if self._database else self._driver.session() as sess:
                await sess.run(
                    query,
                    incident_id=incident_id,
                    opened_at=opened_at,
                    severity=severity,
                    devices=affected_device_ids,
                )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("kg.register_incident_failed", error=str(exc))
            return False


__all__ = ["KnowledgeGraph"]
