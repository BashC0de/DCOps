"""Digital-twin state endpoint. Drives the Three.js view. Ships: Week 10."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/state")
async def twin_state(site: str) -> dict[str, object]:
    """Current rack temps + device states for the twin viewer. Skeleton until Week 10."""
    # TODO(week-10): aggregate latest inlet/outlet temps + device states from
    #                Timescale + Neo4j, return compact JSON for Three.js rendering.
    return {"site": site, "racks": []}
