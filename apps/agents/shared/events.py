"""Inter-agent event schemas.

Purpose:
    Pydantic models for every event that flows on the Redis event bus
    (other than raw `TelemetryEvent`s, which live in apps/ingestion/schema.py).
    Topic conventions are listed in ARCHITECTURE.md § Agent collaboration.

Ships: Week 2 (skeletons), refined per-agent in Weeks 4-9.

The base `BusEvent` carries the audit fields every event needs. Specific
event types extend it with their own payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# --- Topic name constants (single source of truth) --------------------------------

class Topic(StrEnum):
    """Canonical Redis pub/sub topic names. Patterns end with `*`."""

    TELEMETRY_ALL = "telemetry.*"
    PREDICTIONS_FAILURE = "predictions.failure"
    ALERTS_ALL = "alerts.*"
    INCIDENTS_REPORT = "incidents.report"
    RECOMMENDATIONS_ALL = "recommendations.*"
    ACTIONS_EXECUTED = "actions.executed"
    ACTIONS_ROLLED_BACK = "actions.rolled_back"
    FORECASTS_ALL = "forecasts.*"
    QUERY_RESULT = "query.result"
    AUDIT_EVENTS = "audit.events"


# --- Base event -------------------------------------------------------------------

class BusEvent(BaseModel):
    """Audit-bearing envelope every bus event extends."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    site_id: str
    trace_id: UUID | None = None
    parent_event_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Sentinel -> Forensic/Optimizer ----------------------------------------------

class PredictedFailure(BusEvent):
    """Sentinel emits this when its model + rules suggest impending failure."""

    event_type: Literal["predicted_failure"] = "predicted_failure"
    device_id: str
    device_type: str
    failure_kind: str                    # e.g. "gpu_ecc_runaway", "psu_efficiency_drift"
    probability: float = Field(..., ge=0.0, le=1.0)
    horizon_hours: float = Field(..., ge=0.0)
    evidence: dict[str, Any] = Field(default_factory=dict)


# --- Forensic -> Optimizer / dashboard -------------------------------------------

class IncidentReport(BusEvent):
    """Forensic's RCA output."""

    event_type: Literal["incident_report"] = "incident_report"
    incident_id: UUID = Field(default_factory=uuid4)
    affected_device_ids: list[str]
    top_hypotheses: list[dict[str, Any]]   # [{cause, probability, evidence_ids}]
    similar_past_incidents: list[UUID] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    llm_cost_usd: float = 0.0
    llm_model_used: str | None = None


# --- Optimizer/Planner -> Executor (via policy gate) -----------------------------

class Recommendation(BusEvent):
    """A proposed action. Subject to policy evaluation before execution."""

    event_type: Literal["recommendation"] = "recommendation"
    recommendation_id: UUID = Field(default_factory=uuid4)
    kind: str                            # e.g. "workload_migration", "fan_speed_increase"
    target_device_ids: list[str]
    parameters: dict[str, Any]
    estimated_impact: dict[str, float]   # e.g. {"thermal_drop_c": 4.5, "power_saved_w": 200}
    confidence: float = Field(..., ge=0.0, le=1.0)
    requires_human_approval: bool = False


# --- Executor -> Rollback -------------------------------------------------------

class ActionExecuted(BusEvent):
    """Recorded after the Executor calls the (mocked) remediation endpoint."""

    event_type: Literal["action_executed"] = "action_executed"
    recommendation_id: UUID
    action_id: UUID = Field(default_factory=uuid4)
    success: bool
    response_payload: dict[str, Any] = Field(default_factory=dict)
    pre_action_kpis: dict[str, float] = Field(default_factory=dict)


class ActionRolledBack(BusEvent):
    """Rollback Monitor emits when post-action KPIs trip the revert threshold."""

    event_type: Literal["action_rolled_back"] = "action_rolled_back"
    action_id: UUID
    reason: str
    pre_action_kpis: dict[str, float]
    post_action_kpis: dict[str, float]


# --- Planner -> dashboard / Optimizer -------------------------------------------

class CapacityForecast(BusEvent):
    """Planner's 30/60/90-day forecast snapshot."""

    event_type: Literal["capacity_forecast"] = "capacity_forecast"
    horizon_days: int
    series: dict[str, list[float]]       # metric -> daily values
    confidence_intervals: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)


# --- Operator -> dashboard ------------------------------------------------------

class QueryResult(BusEvent):
    """Operator agent response to a natural-language query."""

    event_type: Literal["query_result"] = "query_result"
    request_id: UUID
    question: str
    answer_text: str
    sql_executed: str | None = None
    chart_spec: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    llm_cost_usd: float = 0.0


__all__ = [
    "BusEvent",
    "Topic",
    "PredictedFailure",
    "IncidentReport",
    "Recommendation",
    "ActionExecuted",
    "ActionRolledBack",
    "CapacityForecast",
    "QueryResult",
]
