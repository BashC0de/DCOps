"""Tests for apps/agents/shared/quality/schemas.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.agents.shared.quality.schemas import (
    IncidentRCA,
    OperatorAnswer,
    RCAHypothesis,
    VisionFinding,
)
from apps.ingestion.schema import Severity

pytestmark = pytest.mark.unit


# --- IncidentRCA ----------------------------------------------------------------

def test_incident_rca_accepts_well_formed() -> None:
    rca = IncidentRCA(
        incident_summary="GPU thermal runaway in rack 7",
        top_hypotheses=[
            RCAHypothesis(
                cause="CRAC supply drift",
                probability=0.7,
                evidence_summary="inlet temps climbing across rack",
                affected_device_ids=["fra-h1-r07-srv03"],
            ),
        ],
        confidence=0.8,
        recommended_action="bump CRAC-2 fan to 90%",
    )
    assert rca.top_hypotheses[0].probability == pytest.approx(0.7)


def test_incident_rca_rejects_empty_hypotheses() -> None:
    with pytest.raises(ValidationError):
        IncidentRCA(
            incident_summary="x",
            top_hypotheses=[],
            confidence=0.5,
            recommended_action="y",
        )


def test_incident_rca_all_device_ids_dedupes_and_preserves_order() -> None:
    rca = IncidentRCA(
        incident_summary="x",
        top_hypotheses=[
            RCAHypothesis(cause="a", probability=0.5, evidence_summary="e",
                          affected_device_ids=["d1", "d2"]),
            RCAHypothesis(cause="b", probability=0.3, evidence_summary="e",
                          affected_device_ids=["d2", "d3"]),
        ],
        confidence=0.5,
        recommended_action="x",
    )
    assert rca.all_device_ids() == ["d1", "d2", "d3"]


# --- OperatorAnswer -------------------------------------------------------------

def test_operator_answer_accepts_select() -> None:
    a = OperatorAnswer(
        answer_text="here's the trend",
        sql="SELECT * FROM telemetry WHERE site_id = 'frankfurt'",
        referenced_metrics=["cpu.temp.celsius"],
        confidence=0.9,
    )
    assert a.sql.upper().startswith("SELECT")


def test_operator_answer_accepts_with_cte() -> None:
    a = OperatorAnswer(
        answer_text="x",
        sql="WITH hot AS (SELECT * FROM telemetry) SELECT * FROM hot",
        referenced_metrics=[],
        confidence=0.7,
    )
    assert "WITH" in a.sql.upper()


def test_operator_answer_rejects_insert() -> None:
    with pytest.raises(ValidationError):
        OperatorAnswer(
            answer_text="x",
            sql="INSERT INTO telemetry VALUES (1)",
            referenced_metrics=[],
            confidence=0.5,
        )


def test_operator_answer_rejects_drop_even_inside_select() -> None:
    with pytest.raises(ValidationError):
        OperatorAnswer(
            answer_text="x",
            sql="SELECT * FROM x; DROP TABLE y",
            referenced_metrics=[],
            confidence=0.5,
        )


# --- VisionFinding --------------------------------------------------------------

def test_vision_finding_requires_observations() -> None:
    with pytest.raises(ValidationError):
        VisionFinding(
            finding_summary="x",
            affected_device_ids=[],
            severity=Severity.WARN,
            confidence=0.5,
            evidence_observations=[],
        )


def test_vision_finding_accepts_well_formed() -> None:
    f = VisionFinding(
        finding_summary="amber LED on PSU 2",
        affected_device_ids=["fra-h1-r07-srv03"],
        severity=Severity.ERROR,
        confidence=0.8,
        evidence_observations=["amber LED visible on bottom PSU"],
    )
    assert f.severity is Severity.ERROR
