"""Fleet view materializer.

Every `FLEET_VIEW_INTERVAL_S` seconds, build a fleet-level snapshot:
    - Per site: count of live agents (from heartbeats), most recent
      heartbeat timestamp, list of degraded/missing agents (expected vs
      seen), recent incident counts (via TimescaleStore).
    - Whole-fleet: total live agents, total open incidents, last
      heartbeat across all sites.

Persisted under `fleet:snapshot` in Redis (TTL = 3× the interval) so
the dashboard's home view can read it without re-aggregating per call.

When TimescaleDB isn't connected, the incident counts come back as 0
and the rest of the snapshot still renders.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from apps.agents.shared.event_bus import EventBus
from apps.agents.shared.logging import get_logger
from apps.agents.shared.ts_client import TimescaleStore

log = get_logger(__name__)


_INTERVAL_S = float(os.getenv("FLEET_VIEW_INTERVAL_S", "5"))
_HEARTBEAT_STALE_S = float(os.getenv("FLEET_VIEW_HEARTBEAT_STALE_S", "60"))
_SNAPSHOT_KEY = "fleet:snapshot"
# Agents we EXPECT every site to run. Anything in this set missing from
# the heartbeat scan is reported as "degraded".
_EXPECTED_AGENTS_PER_SITE: tuple[str, ...] = (
    "sentinel",
    "forensic",
    "operator",
    "optimizer",
    "planner",
    "executor",
    "rollback",
)


def _expected_agents() -> tuple[str, ...]:
    raw = os.getenv("FLEET_VIEW_EXPECTED_AGENTS")
    if not raw:
        return _EXPECTED_AGENTS_PER_SITE
    return tuple(a.strip() for a in raw.split(",") if a.strip())


async def build_snapshot(
    bus: EventBus,
    ts: TimescaleStore,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Pure-ish builder. Reads Redis heartbeats + Timescale incident counts."""
    now = now if now is not None else time.time()
    client = getattr(bus, "_client", None)

    sites: dict[str, dict[str, Any]] = {}
    expected = list(_expected_agents())

    if client is not None:
        try:
            keys = [k async for k in client.scan_iter(match="agent:*:*:heartbeat", count=500)]
        except Exception:  # noqa: BLE001
            keys = []
        for key in keys:
            try:
                raw = await client.get(key)
            except Exception:  # noqa: BLE001
                continue
            if raw is None:
                continue
            try:
                hb = json.loads(raw)
            except json.JSONDecodeError:
                continue
            site_id = str(hb.get("site_id", "unknown"))
            agent_name = str(hb.get("agent", "unknown"))
            site = sites.setdefault(
                site_id,
                {
                    "site_id": site_id,
                    "live_agents": [],
                    "most_recent_heartbeat_ts": 0.0,
                    "incidents_last_hour": 0,
                },
            )
            site["live_agents"].append(
                {
                    "agent": agent_name,
                    "last_seen_ts": float(hb.get("last_seen_ts", 0.0)),
                    "pid": hb.get("pid"),
                }
            )
            site["most_recent_heartbeat_ts"] = max(
                float(site["most_recent_heartbeat_ts"]),
                float(hb.get("last_seen_ts", 0.0)),
            )

    # Stale-check + expected-agent diff.
    for site in sites.values():
        live = site["live_agents"]
        # Strip agents whose last_seen is older than the staleness window.
        fresh = [a for a in live if now - float(a["last_seen_ts"]) < _HEARTBEAT_STALE_S]
        site["live_agents"] = fresh
        site["n_live_agents"] = len(fresh)
        live_names = {a["agent"] for a in fresh}
        site["missing_agents"] = sorted(set(expected) - live_names)
        site["status"] = "ok" if not site["missing_agents"] else "degraded"

    # Per-site recent-incident counts.
    if ts.enabled:
        for site_id in list(sites.keys()):
            try:
                rows = await ts.execute_select(
                    "SELECT COUNT(*) AS c FROM incidents "
                    "WHERE site_id = %s AND opened_at >= NOW() - INTERVAL '1 hour'",
                    (site_id,),
                    max_rows=1,
                )
            except Exception:  # noqa: BLE001
                rows = []
            if rows:
                count = rows[0].get("c")
                if isinstance(count, (int, float)):
                    sites[site_id]["incidents_last_hour"] = int(count)

    fleet_status = "ok"
    if any(s["status"] == "degraded" for s in sites.values()):
        fleet_status = "degraded"
    if not sites:
        fleet_status = "empty"

    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "fleet_status": fleet_status,
        "n_sites": len(sites),
        "n_live_agents": sum(s["n_live_agents"] for s in sites.values()),
        "total_incidents_last_hour": sum(s["incidents_last_hour"] for s in sites.values()),
        "sites": sorted(sites.values(), key=lambda s: s["site_id"]),
    }


async def run_fleet_view(
    bus: EventBus | None = None,
    ts: TimescaleStore | None = None,
) -> None:
    """Long-running aggregator loop."""
    bus = bus or EventBus.from_env()
    ts = ts or TimescaleStore.from_env()
    await ts.connect()
    log.info(
        "control_plane.fleet_view.start",
        interval_s=_INTERVAL_S,
        ts_enabled=ts.enabled,
        expected_agents=_expected_agents(),
    )
    client = getattr(bus, "_client", None)
    try:
        while True:
            snapshot = await build_snapshot(bus, ts)
            if client is not None:
                try:
                    await client.set(
                        _SNAPSHOT_KEY,
                        json.dumps(snapshot),
                        ex=int(_INTERVAL_S * 3),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("fleet_view.cache_failed", error=str(exc))
            await asyncio.sleep(_INTERVAL_S)
    finally:
        await ts.close()
        await bus.close()


__all__ = ["run_fleet_view", "build_snapshot"]
