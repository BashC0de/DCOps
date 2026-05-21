"""Planner — capacity forecasting agent.

Purpose:
    Runs hourly (cron-like). Pulls aggregated historical telemetry from
    TimescaleDB and produces 30/60/90-day forecasts for power draw, thermal
    load, GPU utilization. Uses Prophet primarily; falls back to ARIMA for
    short, sparse series. Publishes `CapacityForecast` events.

Ships: Week 7 (see ROADMAP.md).

This agent does NOT subscribe to the bus continuously — its loop is a
scheduled timer. The BaseAgent's `serve()` is not used here; we override
`run()` instead.

Topics:
    out: forecasts.30, forecasts.60, forecasts.90
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from apps.agents.shared.base import BaseAgent


class PlannerAgent(BaseAgent):
    name = "planner"
    subscribed_topic = ""                 # no bus subscription; scheduled loop
    event_model = None

    async def serve(self) -> None:                 # type: ignore[override]
        """Override of BaseAgent.serve(): scheduled loop instead of subscribe()."""
        await self.on_start()
        interval = float(os.getenv("PLANNER_INTERVAL_SEC", "3600"))
        horizon_days = int(os.getenv("PLANNER_HORIZON_DAYS", "90"))
        self.log.info("planner.ready", interval_sec=interval, horizon_days=horizon_days)
        try:
            while not self._stop.is_set():
                await self._tick(horizon_days=horizon_days)
                await asyncio.sleep(interval)
        finally:
            await self.on_stop()

    async def handle(self, event: object) -> None:
        # Not used — Planner does not subscribe.
        raise NotImplementedError

    async def _tick(self, horizon_days: int) -> None:
        now = datetime.now(timezone.utc)
        self.log.info("planner.run", at=now.isoformat(), horizon_days=horizon_days)
        # TODO(week-7): pull TimescaleDB continuous aggregates, fit Prophet per
        #               (site, metric), publish CapacityForecast events.


if __name__ == "__main__":
    PlannerAgent.run()
