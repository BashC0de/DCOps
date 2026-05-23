"""Digital-twin state endpoint.

Returns a compact JSON snapshot for the Three.js viewer:
    site → halls → racks → per-rack thermal aggregate + device states.

Sources:
    TimescaleStore — latest inlet/outlet temp per rack.
    KnowledgeGraph — rack/device topology.

When neither is wired, the route returns a `status=degraded` payload
with empty arrays so the dashboard can still render its shell.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/state")
async def twin_state(request: Request, site: str) -> dict[str, Any]:
    ts = getattr(request.app.state, "ts", None)
    kg = getattr(request.app.state, "kg", None)

    if (ts is None or not ts.enabled) and (kg is None or not kg.enabled):
        return {"site": site, "racks": [], "status": "degraded"}

    # 1. Rack topology from Neo4j (if available).
    racks: list[dict[str, Any]] = []
    if kg is not None and kg.enabled:
        racks = await _racks_for_site(kg, site)

    # 2. Latest inlet/outlet per rack from Timescale (if available).
    if ts is not None and ts.enabled and racks:
        latest = await _latest_inlet_outlet(ts, site)
        for rack in racks:
            rack_id = rack["id"]
            rack["inlet_c"] = latest.get((rack_id, "env.inlet.celsius"))
            rack["outlet_c"] = latest.get((rack_id, "env.outlet.celsius"))

    return {"site": site, "racks": racks}


async def _racks_for_site(kg: Any, site: str) -> list[dict[str, Any]]:
    """Pull `(Rack)-[:LOCATED_IN*]->(Site {id: $site})` with device counts."""
    if not kg.enabled:
        return []
    # We call the driver directly here — no helper exists for this query yet.
    if not hasattr(kg, "_driver") or kg._driver is None:  # noqa: SLF001
        return []
    query = (
        "MATCH (s:Site {id: $site_id})<-[:LOCATED_IN]-(h:Hall)<-[:LOCATED_IN]-(r:Rack) "
        "OPTIONAL MATCH (d:Device)-[:MOUNTED_IN]->(r) "
        "RETURN r.id AS rack_id, r.position AS position, h.id AS hall_id, "
        "       count(d) AS device_count "
        "ORDER BY h.id, r.id"
    )
    try:
        async with kg._driver.session() as sess:  # noqa: SLF001
            result = await sess.run(query, site_id=site)
            return [
                {
                    "id": rec["rack_id"],
                    "hall_id": rec["hall_id"],
                    "position": rec["position"],
                    "device_count": int(rec["device_count"] or 0),
                }
                async for rec in result
            ]
    except Exception:  # noqa: BLE001
        return []


async def _latest_inlet_outlet(ts: Any, site: str) -> dict[tuple[str, str], float]:
    """Map of (rack_id, metric) → latest value within the last 5 minutes."""
    if not ts.enabled:
        return {}
    sql = (
        "SELECT DISTINCT ON (rack_id, metric) rack_id, metric, value_num "
        "FROM telemetry "
        "WHERE site_id = %s "
        "  AND metric IN ('env.inlet.celsius', 'env.outlet.celsius') "
        "  AND time >= NOW() - INTERVAL '5 minutes' "
        "ORDER BY rack_id, metric, time DESC"
    )
    rows = await ts.execute_select(sql, (site,), max_rows=2000)
    out: dict[tuple[str, str], float] = {}
    for r in rows:
        rack_id = r.get("rack_id")
        metric = r.get("metric")
        value = r.get("value_num")
        if isinstance(rack_id, str) and isinstance(metric, str) and isinstance(value, (int, float)):
            out[(rack_id, metric)] = float(value)
    return out
