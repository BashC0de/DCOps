"""Drop a small batch of telemetry samples into TimescaleDB so the
dashboard and API have something to render before the simulator starts.

Idempotent: SELECTs first; only inserts if the table is empty.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402

log = get_logger("seed_telemetry_sample")


SAMPLE_METRICS = [
    ("cpu.temp.celsius", "celsius", 45.0, 70.0),
    ("gpu.temp.celsius", "celsius", 55.0, 80.0),
    ("power.draw.watts", "watts", 200.0, 900.0),
    ("env.inlet.celsius", "celsius", 19.0, 25.0),
]


def main() -> None:
    configure_logging()
    dsn = (
        f"host={os.getenv('TIMESCALE_HOST', 'localhost')} "
        f"port={os.getenv('TIMESCALE_PORT', '5432')} "
        f"dbname={os.getenv('TIMESCALE_DB', 'dcops')} "
        f"user={os.getenv('TIMESCALE_USER', 'dcops')} "
        f"password={os.getenv('TIMESCALE_PASSWORD', 'changeme_timescale')}"
    )

    rng = random.Random(42)
    rows: list[tuple] = []
    now = datetime.now(timezone.utc)
    for site in ("frankfurt", "singapore", "mumbai"):
        for rack_idx in range(3):
            for srv_idx in range(3):
                device_id = f"{site}-h1-r{rack_idx + 1:02d}-srv{srv_idx + 1:02d}"
                rack_id = f"{site}-h1-r{rack_idx + 1:02d}"
                for metric, unit, lo, hi in SAMPLE_METRICS:
                    for minute_ago in range(60):
                        ts = now - timedelta(minutes=minute_ago)
                        rows.append((
                            ts, site, f"{site}-h1", rack_id, device_id, "server",
                            metric, rng.uniform(lo, hi), None, unit, "info", "{}",
                        ))
    log.info("seed_telemetry_sample.prepared", rows=len(rows))

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM telemetry")
            (existing,) = cur.fetchone()  # type: ignore[misc]
            if existing > 0:
                log.info("seed_telemetry_sample.skip", existing=existing)
                return
            cur.executemany(
                "INSERT INTO telemetry "
                "(time, site_id, hall_id, rack_id, device_id, device_type, "
                " metric, value_num, value_str, unit, severity, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                rows,
            )
        conn.commit()
    log.info("seed_telemetry_sample.done")


if __name__ == "__main__":
    main()
