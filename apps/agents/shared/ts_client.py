"""Async TimescaleDB client wrapper.

Built on `psycopg3` (already a runtime dep) with the async connection pool.
Connection details from env vars
(`TIMESCALE_HOST`, `TIMESCALE_PORT`, `TIMESCALE_DB`, `TIMESCALE_USER`,
`TIMESCALE_PASSWORD`).

Provides:
    - `recent_telemetry(device_id, window_s)` — telemetry rows in a window
    - `insert_telemetry(events)` — bulk insert path used by ingestion
    - `insert_incident(...)` — persist a Forensic IncidentReport
    - `execute_select(sql)` — Operator's read-only path; refuses non-SELECT

Graceful degradation:
    `from_env()` always succeeds. `connect()` returns False when the
    server is unreachable. Methods that need the DB return safe defaults
    when disabled.

Schema reference: `infra/timescale/init/01_schema.sql`.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

log = get_logger(__name__)


# Tokens that must NEVER appear in an Operator-submitted SELECT.
# Defense-in-depth — the Pydantic schema validates too, but the DB layer
# refuses with an exception on any breach to keep audit logs honest.
_FORBIDDEN_SQL_TOKENS = (
    "INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "ALTER ",
    "GRANT ", "REVOKE ", "CREATE ", " INTO ", "COPY ",
)


class TimescaleStore:
    """Async wrapper around a psycopg3 connection pool."""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        min_size: int = 1,
        max_size: int = 5,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._min_size = min_size
        self._max_size = max_size
        self._pool: AsyncConnectionPool | None = None

    @classmethod
    def from_env(cls) -> TimescaleStore:
        return cls(
            host=os.getenv("TIMESCALE_HOST", "timescaledb"),
            port=int(os.getenv("TIMESCALE_PORT", "5432")),
            database=os.getenv("TIMESCALE_DB", "dcops"),
            user=os.getenv("TIMESCALE_USER", "dcops"),
            password=os.getenv("TIMESCALE_PASSWORD", "dcops"),
        )

    # --- lifecycle ------------------------------------------------------------

    def _dsn(self) -> str:
        return (
            f"host={self._host} port={self._port} "
            f"dbname={self._database} user={self._user} "
            f"password={self._password}"
        )

    async def connect(self) -> bool:
        if self._pool is not None:
            return True
        try:
            from psycopg_pool import AsyncConnectionPool
        except ImportError:
            log.warning("ts.import_failed", note="`psycopg-pool` not installed")
            return False
        try:
            pool = AsyncConnectionPool(
                conninfo=self._dsn(),
                min_size=self._min_size,
                max_size=self._max_size,
                open=False,
                kwargs={"autocommit": True},
            )
            await pool.open(wait=True, timeout=10.0)
            self._pool = pool
        except Exception as exc:  # noqa: BLE001
            log.warning("ts.connect_failed", host=self._host, error=str(exc))
            self._pool = None
            return False
        log.info("ts.connected", host=self._host, db=self._database)
        return True

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def enabled(self) -> bool:
        return self._pool is not None

    # --- reads ----------------------------------------------------------------

    async def recent_telemetry(
        self,
        device_id: str,
        window_s: int = 300,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return telemetry rows for `device_id` within the last `window_s` seconds."""
        if self._pool is None:
            return []
        query = """
            SELECT time, metric, value_num, value_str, unit, severity, metadata
              FROM telemetry
             WHERE device_id = %s
               AND time >= NOW() - (%s || ' seconds')::interval
             ORDER BY time DESC
             LIMIT %s
        """
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (device_id, str(window_s), limit))
                    cols = [d.name for d in cur.description or []]
                    rows = await cur.fetchall()
                    return [dict(zip(cols, r, strict=False)) for r in rows]
        except Exception as exc:  # noqa: BLE001
            log.warning("ts.recent_telemetry_failed", device_id=device_id, error=str(exc))
            return []

    async def execute_select(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        max_rows: int = 1000,
    ) -> list[dict[str, Any]]:
        """Run a read-only SELECT. Refuses anything containing forbidden tokens.

        Operator agent uses this to execute its NL-generated SQL. The
        Pydantic schema validates first, but this layer enforces again so
        unauthorized SQL never reaches the database.
        """
        if self._pool is None:
            return []
        upper = " " + sql.upper() + " "
        for tok in _FORBIDDEN_SQL_TOKENS:
            if tok in upper:
                raise ValueError(f"refusing SQL containing forbidden token: {tok.strip()}")
        stripped = sql.lstrip("(").lstrip().upper()
        if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
            raise ValueError("execute_select only accepts SELECT / WITH ... SELECT")

        try:
            async with self._pool.connection() as conn:
                # Belt-and-braces: read-only transaction at the DB layer too.
                async with conn.transaction(force_rollback=True):
                    async with conn.cursor() as cur:
                        await cur.execute("SET TRANSACTION READ ONLY")
                        await cur.execute(sql, params)
                        cols = [d.name for d in cur.description or []]
                        rows = await cur.fetchmany(max_rows)
                        return [dict(zip(cols, r, strict=False)) for r in rows]
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("ts.execute_select_failed", error=str(exc))
            return []

    # --- writes ---------------------------------------------------------------

    async def insert_telemetry(self, events: list[dict[str, Any]]) -> int:
        """Bulk insert telemetry rows. Returns the count inserted."""
        if self._pool is None or not events:
            return 0
        cols = (
            "time", "site_id", "hall_id", "rack_id", "device_id",
            "device_type", "metric", "value_num", "value_str",
            "unit", "severity", "metadata",
        )
        placeholders = ", ".join(["%s"] * len(cols))
        sql = (
            f"INSERT INTO telemetry ({', '.join(cols)}) "
            f"VALUES ({placeholders})"
        )

        def _row(e: dict[str, Any]) -> tuple[Any, ...]:
            value = e.get("value")
            value_num = value if isinstance(value, (int, float)) else None
            value_str = value if isinstance(value, str) else None
            return (
                e.get("timestamp"),
                e.get("site_id"),
                e.get("hall_id"),
                e.get("rack_id"),
                e.get("device_id"),
                e.get("device_type"),
                e.get("metric"),
                value_num,
                value_str,
                e.get("unit"),
                e.get("severity", "info"),
                e.get("metadata", {}),
            )

        rows = [_row(e) for e in events]
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(sql, rows)
            return len(rows)
        except Exception as exc:  # noqa: BLE001
            log.warning("ts.insert_telemetry_failed", n=len(rows), error=str(exc))
            return 0

    async def insert_incident(
        self,
        *,
        incident_id: UUID | str,
        opened_at: datetime,
        site_id: str,
        severity: str,
        affected_devices: list[str],
        top_hypotheses: list[dict[str, Any]],
        confidence: float,
        llm_cost_usd: float = 0.0,
        llm_model_used: str | None = None,
        trace_id: UUID | str | None = None,
    ) -> bool:
        """Persist a Forensic IncidentReport into the `incidents` table."""
        if self._pool is None:
            return False
        import json as _json
        query = """
            INSERT INTO incidents (
                incident_id, opened_at, site_id, severity,
                affected_devices, top_hypotheses, confidence,
                llm_cost_usd, llm_model_used, trace_id
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT (incident_id) DO NOTHING
        """
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        query,
                        (
                            str(incident_id),
                            opened_at,
                            site_id,
                            severity,
                            affected_devices,
                            _json.dumps(top_hypotheses),
                            confidence,
                            llm_cost_usd,
                            llm_model_used,
                            str(trace_id) if trace_id else None,
                        ),
                    )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("ts.insert_incident_failed", incident_id=str(incident_id), error=str(exc))
            return False


__all__ = ["TimescaleStore"]
