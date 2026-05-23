"""Synthetic runbooks corpus for the Operator agent's NL→SQL retrieval.

Each entry pairs a natural-language question shape with an example SQL
template plus the canonical metric(s) it touches. The question text is
what gets embedded; the rest is metadata that the LLM uses as a few-shot
exemplar for generating SQL from a similar incoming question.

Curated to cover the kinds of questions an SRE actually asks an
operations dashboard. Realistic-ish — drawn from common data center
observability runbook templates.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Runbook:
    id: str
    question: str          # natural-language exemplar (embedded for similarity)
    sql_template: str      # parameterized SQL the LLM should pattern-match on
    metrics: tuple[str, ...]
    category: str          # "thermal" | "power" | "gpu" | "network" | "storage" | "fleet"
    notes: str             # human-readable hint that goes into the prompt context


CORPUS: tuple[Runbook, ...] = (
    # --- Thermal -----------------------------------------------------------
    Runbook(
        id="rb-thermal-001",
        question="Which racks ran the hottest in the last 24 hours?",
        sql_template=(
            "SELECT rack_id, MAX(value_num) AS peak_c "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'env.outlet.celsius' "
            "  AND time >= NOW() - INTERVAL '24 hours' "
            "GROUP BY rack_id ORDER BY peak_c DESC LIMIT 10"
        ),
        metrics=("env.outlet.celsius",),
        category="thermal",
        notes="Aggregate peak outlet temp per rack; useful for spotting hotspots.",
    ),
    Runbook(
        id="rb-thermal-002",
        question="Show me inlet temperature trend for hall fra-h1 over the past hour.",
        sql_template=(
            "SELECT time, AVG(value_num) AS inlet_c "
            "FROM telemetry "
            "WHERE site_id = $SITE AND hall_id = $HALL "
            "  AND metric = 'env.inlet.celsius' "
            "  AND time >= NOW() - INTERVAL '1 hour' "
            "GROUP BY time ORDER BY time"
        ),
        metrics=("env.inlet.celsius",),
        category="thermal",
        notes="Time-series mean across the hall — good as a Plotly line.",
    ),
    Runbook(
        id="rb-thermal-003",
        question="Are any CPU temps above 85 degrees right now?",
        sql_template=(
            "SELECT device_id, value_num AS cpu_temp_c, time "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'cpu.temp.celsius' "
            "  AND value_num > 85 "
            "  AND time >= NOW() - INTERVAL '5 minutes' "
            "ORDER BY value_num DESC LIMIT 20"
        ),
        metrics=("cpu.temp.celsius",),
        category="thermal",
        notes="Hot-CPU outliers; supports drill-down by device.",
    ),

    # --- Power -------------------------------------------------------------
    Runbook(
        id="rb-power-001",
        question="What is the total power draw for site frankfurt over the last hour?",
        sql_template=(
            "SELECT time, SUM(value_num) AS site_watts "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'power.draw.watts' "
            "  AND time >= NOW() - INTERVAL '1 hour' "
            "GROUP BY time ORDER BY time"
        ),
        metrics=("power.draw.watts",),
        category="power",
        notes="Site-level draw timeseries.",
    ),
    Runbook(
        id="rb-power-002",
        question="Which PDUs are above 80% load capacity?",
        sql_template=(
            "SELECT DISTINCT ON (device_id) device_id, value_num AS load_pct, time "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'pdu.load.percent' "
            "  AND time >= NOW() - INTERVAL '5 minutes' "
            "ORDER BY device_id, time DESC"
        ),
        metrics=("pdu.load.percent",),
        category="power",
        notes="Filter > 80 in the post-query application or add WHERE value_num > 80.",
    ),
    Runbook(
        id="rb-power-003",
        question="Show me PSU efficiency drift across the fleet over the past 6 hours.",
        sql_template=(
            "SELECT time, AVG(value_num) AS avg_eff "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'psu.efficiency.percent' "
            "  AND time >= NOW() - INTERVAL '6 hours' "
            "GROUP BY time ORDER BY time"
        ),
        metrics=("psu.efficiency.percent",),
        category="power",
        notes="Falling trend usually precedes PSU failure.",
    ),

    # --- GPU --------------------------------------------------------------
    Runbook(
        id="rb-gpu-001",
        question="What's the GPU utilization across all GPUs in the last 10 minutes?",
        sql_template=(
            "SELECT device_id, AVG(value_num) AS util_pct "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'gpu.util.percent' "
            "  AND time >= NOW() - INTERVAL '10 minutes' "
            "GROUP BY device_id ORDER BY util_pct DESC LIMIT 50"
        ),
        metrics=("gpu.util.percent",),
        category="gpu",
        notes="Per-GPU average util — useful for finding stranded capacity.",
    ),
    Runbook(
        id="rb-gpu-002",
        question="Did any GPUs report XID errors in the last 24 hours?",
        sql_template=(
            "SELECT device_id, MAX(value_num) AS xid_code, MAX(time) AS last_seen "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'gpu.xid.code' "
            "  AND value_num > 0 "
            "  AND time >= NOW() - INTERVAL '24 hours' "
            "GROUP BY device_id"
        ),
        metrics=("gpu.xid.code",),
        category="gpu",
        notes="Any non-zero XID is noteworthy; fatal codes (43,48,63,…) need immediate action.",
    ),
    Runbook(
        id="rb-gpu-003",
        question="Which GPUs had the highest correctable ECC counts today?",
        sql_template=(
            "SELECT device_id, SUM(value_num) AS ecc_total "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'gpu.ecc.correctable' "
            "  AND time >= NOW() - INTERVAL '1 day' "
            "GROUP BY device_id ORDER BY ecc_total DESC LIMIT 20"
        ),
        metrics=("gpu.ecc.correctable",),
        category="gpu",
        notes="Sustained correctable ECC often precedes uncorrectable failure.",
    ),

    # --- Storage / disk ---------------------------------------------------
    Runbook(
        id="rb-storage-001",
        question="List drives with growing reallocated sector counts.",
        sql_template=(
            "SELECT device_id, MAX(value_num) - MIN(value_num) AS delta, MAX(value_num) AS latest "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'disk.reallocated.sectors' "
            "  AND time >= NOW() - INTERVAL '7 days' "
            "GROUP BY device_id HAVING MAX(value_num) - MIN(value_num) > 0 "
            "ORDER BY delta DESC LIMIT 20"
        ),
        metrics=("disk.reallocated.sectors",),
        category="storage",
        notes="Backblaze pattern — increasing reallocations = imminent failure.",
    ),
    Runbook(
        id="rb-storage-002",
        question="Are any drives running hot?",
        sql_template=(
            "SELECT DISTINCT ON (device_id) device_id, value_num AS disk_temp_c, time "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'disk.temp.celsius' "
            "  AND time >= NOW() - INTERVAL '15 minutes' "
            "  AND value_num > 50 "
            "ORDER BY device_id, time DESC"
        ),
        metrics=("disk.temp.celsius",),
        category="storage",
        notes="Disk temps > 50°C correlate with shorter lifespan.",
    ),

    # --- Network ----------------------------------------------------------
    Runbook(
        id="rb-network-001",
        question="Which switches have ports down right now?",
        sql_template=(
            "SELECT DISTINCT ON (device_id) device_id, value_num AS port_up_count, time "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'net.port.up' "
            "  AND time >= NOW() - INTERVAL '5 minutes' "
            "  AND value_num = 0 "
            "ORDER BY device_id, time DESC"
        ),
        metrics=("net.port.up",),
        category="network",
        notes="Port down for > 5 minutes is an actionable alert.",
    ),
    Runbook(
        id="rb-network-002",
        question="What is the input bandwidth trend for switch fra-h1-r07-tor?",
        sql_template=(
            "SELECT time, value_num AS bps_in "
            "FROM telemetry "
            "WHERE site_id = $SITE AND device_id = $DEVICE "
            "  AND metric = 'net.bps.in' "
            "  AND time >= NOW() - INTERVAL '1 hour' "
            "ORDER BY time"
        ),
        metrics=("net.bps.in",),
        category="network",
        notes="Time-series for one device; Plotly line.",
    ),

    # --- Fleet / cross-cutting --------------------------------------------
    Runbook(
        id="rb-fleet-001",
        question="How many devices have critical-severity events in the last hour?",
        sql_template=(
            "SELECT COUNT(DISTINCT device_id) AS critical_devices "
            "FROM telemetry "
            "WHERE site_id = $SITE AND severity = 'critical' "
            "  AND time >= NOW() - INTERVAL '1 hour'"
        ),
        metrics=("*",),
        category="fleet",
        notes="Fleet-wide critical count; scalar answer.",
    ),
    Runbook(
        id="rb-fleet-002",
        question="Compare power draw between Frankfurt and Singapore over the last 12 hours.",
        sql_template=(
            "SELECT time, site_id, SUM(value_num) AS site_watts "
            "FROM telemetry "
            "WHERE site_id IN ('frankfurt', 'singapore') "
            "  AND metric = 'power.draw.watts' "
            "  AND time >= NOW() - INTERVAL '12 hours' "
            "GROUP BY time, site_id ORDER BY time"
        ),
        metrics=("power.draw.watts",),
        category="fleet",
        notes="Multi-site comparison — Plotly multi-line.",
    ),
    Runbook(
        id="rb-fleet-003",
        question="Show me everything currently anomalous for site mumbai.",
        sql_template=(
            "SELECT device_id, metric, value_num, severity, time "
            "FROM telemetry "
            "WHERE site_id = 'mumbai' "
            "  AND severity IN ('error', 'critical') "
            "  AND time >= NOW() - INTERVAL '10 minutes' "
            "ORDER BY severity DESC, time DESC LIMIT 100"
        ),
        metrics=("*",),
        category="fleet",
        notes="Recent error/critical events for a site.",
    ),

    # --- CRAC / cooling ---------------------------------------------------
    Runbook(
        id="rb-cooling-001",
        question="What is the supply temperature for each CRAC unit right now?",
        sql_template=(
            "SELECT DISTINCT ON (device_id) device_id, value_num AS supply_c, time "
            "FROM telemetry "
            "WHERE site_id = $SITE AND metric = 'crac.supply.celsius' "
            "  AND time >= NOW() - INTERVAL '5 minutes' "
            "ORDER BY device_id, time DESC"
        ),
        metrics=("crac.supply.celsius",),
        category="thermal",
        notes="Latest supply temp per CRAC; baseline for thermal incidents.",
    ),
    Runbook(
        id="rb-cooling-002",
        question="Show the delta between supply and return temperatures for CRACs in fra-h1.",
        sql_template=(
            "SELECT time, "
            "  MAX(CASE WHEN metric = 'crac.return.celsius' THEN value_num END) "
            "  - MAX(CASE WHEN metric = 'crac.supply.celsius' THEN value_num END) AS delta_c "
            "FROM telemetry "
            "WHERE site_id = $SITE AND hall_id = $HALL "
            "  AND metric IN ('crac.return.celsius', 'crac.supply.celsius') "
            "  AND time >= NOW() - INTERVAL '1 hour' "
            "GROUP BY time ORDER BY time"
        ),
        metrics=("crac.supply.celsius", "crac.return.celsius"),
        category="thermal",
        notes="Return - supply ≈ heat removed; a falling delta = cooling capacity loss.",
    ),
)


def by_category() -> dict[str, list[Runbook]]:
    out: dict[str, list[Runbook]] = {}
    for r in CORPUS:
        out.setdefault(r.category, []).append(r)
    return out


__all__ = ["Runbook", "CORPUS", "by_category"]
