"""Pydantic output schemas for the LLM-using agents.

These are the *shapes* the LLM must produce. They're consumed by the
structured-output quality layer (`call_structured`) to grammar-constrain
the model and validate at parse time.

Each schema carries a `confidence` field so the escalation layer can read
it directly (no extra parsing). Each carries identifiers that the KG
grounding layer cross-checks against Neo4j + `CanonicalMetric`.

Keeping schemas centralized here (instead of inside each agent module)
lets unit tests import them without dragging in the whole agent stack.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.ingestion.schema import Severity


# --- Forensic — RCA --------------------------------------------------------------

class RCAHypothesis(BaseModel):
    """One candidate root cause for an incident."""

    model_config = ConfigDict(extra="forbid")

    cause: str = Field(min_length=1, description="Short label for the candidate cause.")
    probability: float = Field(ge=0.0, le=1.0)
    evidence_summary: str = Field(
        min_length=1,
        description="Which observations in the context support this hypothesis.",
    )
    affected_device_ids: list[str] = Field(
        default_factory=list,
        description="Device IDs implicated — must exist in the KG.",
    )


class IncidentRCA(BaseModel):
    """Forensic agent's structured output for a single incident."""

    model_config = ConfigDict(extra="forbid")

    incident_summary: str = Field(min_length=1)
    top_hypotheses: list[RCAHypothesis] = Field(min_length=1, max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str = Field(min_length=1)

    def all_device_ids(self) -> list[str]:
        """Flatten device IDs across hypotheses, preserving first-seen order."""
        seen: dict[str, None] = {}
        for h in self.top_hypotheses:
            for d in h.affected_device_ids:
                seen.setdefault(d, None)
        return list(seen.keys())


# --- Operator — NL→SQL -----------------------------------------------------------

class OperatorAnswer(BaseModel):
    """Operator agent's response to a natural-language query."""

    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(min_length=1)
    sql: str = Field(
        min_length=1,
        description="A single SELECT statement. DDL/DML is refused upstream.",
    )
    referenced_metrics: list[str] = Field(
        default_factory=list,
        description="Canonical metric names referenced in the SQL.",
    )
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("sql")
    @classmethod
    def _must_be_select(cls, v: str) -> str:
        stripped = v.strip().lstrip("(").lstrip().upper()
        if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
            raise ValueError("sql must be a SELECT (or WITH ... SELECT) statement")
        # Defense-in-depth: refuse any tokens that mutate state.
        forbidden = (
            "INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "ALTER ",
            "GRANT ", "REVOKE ", "CREATE ", " INTO ",
        )
        upper = " " + v.upper() + " "
        for tok in forbidden:
            if tok in upper:
                raise ValueError(f"sql contains forbidden token: {tok.strip()}")
        return v


# --- Vision — image analysis -----------------------------------------------------

class VisionFinding(BaseModel):
    """Vision agent's structured output from a rack/thermal image."""

    model_config = ConfigDict(extra="forbid")

    finding_summary: str = Field(min_length=1)
    affected_device_ids: list[str] = Field(default_factory=list)
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_observations: list[str] = Field(
        min_length=1,
        description="Concrete things visible in the image that support the finding.",
    )


__all__ = [
    "IncidentRCA",
    "OperatorAnswer",
    "RCAHypothesis",
    "VisionFinding",
]
