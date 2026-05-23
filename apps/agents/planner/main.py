"""Planner — capacity forecasting agent.

Loop:
    Every `PLANNER_TICK_SEC` seconds (default 3600), for each
    (site, metric) in `PLANNER_FORECAST_SETS`:
      1. Pull historical daily aggregates from TimescaleDB.
      2. Fit a Prophet model (or fall back to a linear extrapolation).
      3. Publish a `CapacityForecast` event on `forecasts.<horizon>`.
      4. Cache the forecast at `forecasts:<site>:<metric>:<horizon>` in
         Redis so the dashboard can fetch it without re-subscribing.

The agent doesn't subscribe to any event stream — it's a scheduled
worker. We override `serve()` to run the tick loop in place of the
normal bus subscription.

Topics:
    in:  (timer only)
    out: forecasts.<horizon>      e.g. forecasts.30, forecasts.60, forecasts.90
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from apps.agents.planner.forecaster import ForecastResult, forecast
from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import CapacityForecast
from apps.agents.shared.ts_client import TimescaleStore


_DEFAULT_FORECAST_SETS = (
    ("frankfurt", "power.draw.watts"),
    ("frankfurt", "env.inlet.celsius"),
    ("frankfurt", "gpu.util.percent"),
    ("singapore", "power.draw.watts"),
    ("singapore", "env.inlet.celsius"),
    ("mumbai",    "power.draw.watts"),
    ("mumbai",    "env.inlet.celsius"),
)

_TICK_S = float(os.getenv("PLANNER_TICK_SEC", "3600"))
_HISTORY_DAYS = int(os.getenv("PLANNER_HISTORY_DAYS", "30"))
_HORIZONS = (30, 60, int(os.getenv("PLANNER_HORIZON_DAYS", "90")))
_REDIS_KEY_TTL_S = int(os.getenv("PLANNER_REDIS_TTL_S", "7200"))   # 2 hours


def _redis_key(site_id: str, metric: str, horizon: int) -> str:
    return f"forecasts:{site_id}:{metric}:{horizon}"


def _forecast_sets() -> tuple[tuple[str, str], ...]:
    raw = os.getenv("PLANNER_FORECAST_SETS")
    if not raw:
        return _DEFAULT_FORECAST_SETS
    out: list[tuple[str, str]] = []
    for token in raw.split(","):
        if ":" not in token:
            continue
        site, metric = token.split(":", 1)
        out.append((site.strip(), metric.strip()))
    return tuple(out) or _DEFAULT_FORECAST_SETS


class PlannerAgent(BaseAgent):
    name = "planner"
    subscribed_topic = "planner.never_used"   # no real subscription; override serve()
    event_model = None

    async def on_start(self) -> None:
        await super().on_start()
        self.ts = TimescaleStore.from_env()
        await self.ts.connect()
        self.log.info(
            "planner.ready",
            tick_s=_TICK_S,
            horizons=_HORIZONS,
            forecast_sets=len(_forecast_sets()),
            ts_enabled=self.ts.enabled,
        )

    async def on_stop(self) -> None:
        await self.ts.close()
        await super().on_stop()

    async def serve(self) -> None:
        """Scheduled tick loop in place of normal bus subscription."""
        await self.on_start()
        self._install_signal_handlers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            await self._run_tick()  # first tick fires immediately
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=_TICK_S)
                except asyncio.TimeoutError:
                    await self._run_tick()
        finally:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await self.on_stop()

    async def handle(self, event):  # type: ignore[override]  # noqa: ANN001
        # Required by BaseAgent's abstract — Planner doesn't use it.
        return

    # --- tick body -------------------------------------------------------------

    async def _run_tick(self) -> None:
        sets = _forecast_sets()
        for site_id, metric in sets:
            try:
                await self._forecast_one(site_id=site_id, metric=metric)
            except Exception as exc:  # noqa: BLE001
                self.log.exception(
                    "planner.tick_failed", site=site_id, metric=metric, error=str(exc)
                )

    async def _forecast_one(self, *, site_id: str, metric: str) -> None:
        history = await self._pull_history(site_id=site_id, metric=metric)
        for horizon in _HORIZONS:
            result = await asyncio.to_thread(
                forecast,
                site_id=site_id,
                metric=metric,
                history=history,
                horizon_days=horizon,
            )
            await self._publish_and_cache(result)

    async def _pull_history(
        self, *, site_id: str, metric: str
    ) -> list[tuple[datetime, float]]:
        """Daily aggregate of `metric` for `site_id` over the last N days."""
        if not self.ts.enabled:
            return _synthetic_history(metric=metric, days=_HISTORY_DAYS)
        sql = (
            "SELECT time_bucket('1 day', time) AS bucket, AVG(value_num) AS y "
            "FROM telemetry "
            "WHERE site_id = %s AND metric = %s "
            "  AND time >= NOW() - (%s || ' days')::interval "
            "GROUP BY bucket ORDER BY bucket"
        )
        try:
            rows = await self.ts.execute_select(
                sql, (site_id, metric, str(_HISTORY_DAYS)), max_rows=400,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning("planner.ts_query_failed", error=str(exc))
            return _synthetic_history(metric=metric, days=_HISTORY_DAYS)

        history: list[tuple[datetime, float]] = []
        for r in rows:
            bucket = r.get("bucket")
            y = r.get("y")
            if isinstance(bucket, datetime) and isinstance(y, (int, float)):
                history.append(
                    (bucket if bucket.tzinfo else bucket.replace(tzinfo=timezone.utc), float(y))
                )
            elif isinstance(bucket, str) and isinstance(y, (int, float)):
                try:
                    ts = datetime.fromisoformat(bucket.replace("Z", "+00:00"))
                except ValueError:
                    continue
                history.append((ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc), float(y)))
        if not history:
            return _synthetic_history(metric=metric, days=_HISTORY_DAYS)
        return history

    async def _publish_and_cache(self, result: ForecastResult) -> None:
        event = CapacityForecast(
            site_id=result.site_id,
            horizon_days=result.horizon_days,
            series={result.metric: result.values},
            confidence_intervals={
                result.metric: [
                    (low, high) for low, high in zip(result.lowers, result.uppers, strict=False)
                ]
            },
            metadata={"method": result.method, "notes": result.notes},
        )
        topic = f"forecasts.{result.horizon_days}"
        try:
            await self.bus.publish(topic, event)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("planner.publish_failed", topic=topic, error=str(exc))

        client = getattr(self.bus, "_client", None)
        if client is not None:
            try:
                payload = event.model_dump_json()
                key = _redis_key(result.site_id, result.metric, result.horizon_days)
                await client.set(key, payload, ex=_REDIS_KEY_TTL_S)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("planner.cache_failed", error=str(exc))

        self.log.info(
            "planner.published",
            site=result.site_id,
            metric=result.metric,
            horizon=result.horizon_days,
            method=result.method,
            n_points=len(result.points),
        )


# --- helpers ------------------------------------------------------------------

def _synthetic_history(
    *,
    metric: str,
    days: int,
) -> list[tuple[datetime, float]]:
    """Generate plausible daily history when TS is empty/unavailable."""
    base = {
        "power.draw.watts":     1_500_000.0,
        "env.inlet.celsius":    22.0,
        "gpu.util.percent":     55.0,
    }.get(metric, 100.0)
    out: list[tuple[datetime, float]] = []
    now = datetime.now(timezone.utc)
    for i in range(days, 0, -1):
        ts = now - timedelta(days=i)
        trend = (days - i) * 0.5
        weekly = 2.0 * (i % 7 - 3) / 3.0
        out.append((ts, base + trend + weekly))
    return out


__all__ = ["PlannerAgent", "_redis_key"]


if __name__ == "__main__":
    PlannerAgent.run()
