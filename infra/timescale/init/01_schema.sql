-- ============================================================================
-- DCOps Copilot — TimescaleDB schema
-- ============================================================================
-- Runs once on first TimescaleDB container start (docker-entrypoint-initdb.d).
-- Defines the telemetry hypertable and supporting indexes/retention policies.
--
-- Ships: Week 1 (table); retention policy + continuous aggregates land Week 2.
-- ============================================================================

\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ----------------------------------------------------------------------------
-- Main telemetry table.
-- Wide-table layout: one row per metric sample. Cardinality is moderate
-- because we have a frozen `metric` catalog (see apps/ingestion/schema.py).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telemetry (
    time         TIMESTAMPTZ      NOT NULL,
    site_id      TEXT             NOT NULL,
    hall_id      TEXT             NOT NULL,
    rack_id      TEXT             NOT NULL,
    device_id    TEXT             NOT NULL,
    device_type  TEXT             NOT NULL,
    metric       TEXT             NOT NULL,
    value_num    DOUBLE PRECISION,        -- populated when value is numeric
    value_str    TEXT,                    -- populated when value is a string (e.g. XID code)
    unit         TEXT,
    severity     TEXT             NOT NULL DEFAULT 'info',
    metadata     JSONB            NOT NULL DEFAULT '{}'::jsonb
);

-- Convert to hypertable partitioned by time (1-day chunks).
SELECT create_hypertable(
    'telemetry', by_range('time', INTERVAL '1 day'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_telemetry_site_time
    ON telemetry (site_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_telemetry_device_metric_time
    ON telemetry (device_id, metric, time DESC);

CREATE INDEX IF NOT EXISTS idx_telemetry_rack_time
    ON telemetry (rack_id, time DESC);

-- TODO(week-2): enable compression for chunks older than 1 day:
-- ALTER TABLE telemetry SET (timescaledb.compress, timescaledb.compress_segmentby = 'device_id, metric');
-- SELECT add_compression_policy('telemetry', INTERVAL '1 day');

-- TODO(week-2): 7-day raw retention; downsampled summary tables for older data.
-- SELECT add_retention_policy('telemetry', INTERVAL '7 days');

-- ----------------------------------------------------------------------------
-- Incidents table (Forensic agent output). Mirrors the IncidentReport event.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    incident_id        UUID PRIMARY KEY,
    opened_at          TIMESTAMPTZ NOT NULL,
    closed_at          TIMESTAMPTZ,
    site_id            TEXT NOT NULL,
    severity           TEXT NOT NULL,
    affected_devices   TEXT[] NOT NULL,
    top_hypotheses     JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence         DOUBLE PRECISION,
    llm_cost_usd       DOUBLE PRECISION DEFAULT 0,
    llm_model_used     TEXT,
    trace_id           UUID
);

CREATE INDEX IF NOT EXISTS idx_incidents_site_opened
    ON incidents (site_id, opened_at DESC);

-- ----------------------------------------------------------------------------
-- Actions table (Executor + Rollback output).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actions (
    action_id          UUID PRIMARY KEY,
    recommendation_id  UUID NOT NULL,
    executed_at        TIMESTAMPTZ NOT NULL,
    site_id            TEXT NOT NULL,
    kind               TEXT NOT NULL,
    target_devices     TEXT[] NOT NULL,
    success            BOOLEAN NOT NULL,
    rolled_back_at     TIMESTAMPTZ,
    rollback_reason    TEXT,
    pre_action_kpis    JSONB NOT NULL DEFAULT '{}'::jsonb,
    post_action_kpis   JSONB
);

CREATE INDEX IF NOT EXISTS idx_actions_site_executed
    ON actions (site_id, executed_at DESC);
