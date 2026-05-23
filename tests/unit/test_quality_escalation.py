"""Tests for apps/agents/shared/quality/escalation.py."""

from __future__ import annotations

import pytest

from apps.agents.shared.llm_router import ModelTier, TaskClass
from apps.agents.shared.quality.escalation import (
    parse_confidence,
    strip_confidence_tag,
    with_escalation,
)

pytestmark = pytest.mark.unit


def test_parse_confidence_finds_tag() -> None:
    assert parse_confidence("answer text\n[CONFIDENCE: 0.82]") == pytest.approx(0.82)
    assert parse_confidence("[confidence: 0.5]") == pytest.approx(0.5)
    assert parse_confidence("[CONFIDENCE: 1.0]") == 1.0


def test_parse_confidence_clamps_out_of_range() -> None:
    assert parse_confidence("[CONFIDENCE: 1.5]") == 1.0
    assert parse_confidence("[CONFIDENCE: -0.2]") == 0.0


def test_parse_confidence_missing_returns_none() -> None:
    assert parse_confidence("no tag here") is None
    assert parse_confidence("[CONFIDENCE: not-a-number]") is None


def test_strip_confidence_tag() -> None:
    assert strip_confidence_tag("answer\n[CONFIDENCE: 0.5]") == "answer"
    assert strip_confidence_tag("answer") == "answer"


async def test_no_escalation_when_confidence_high(make_router, fake_backend) -> None:
    fake_backend.replies = ["RCA finding\n[CONFIDENCE: 0.9]"]
    router = make_router()

    result = await with_escalation(
        router,
        task_class=TaskClass.RCA,
        system="Diagnose.",
        messages=[{"role": "user", "content": "incident"}],
        threshold=0.65,
    )
    # Only the fast tier was hit.
    assert len(fake_backend.calls) == 1
    assert result.tier_used == ModelTier.HAIKU
    assert result.escalated is False
    # Tag stripped from returned text.
    assert "[CONFIDENCE" not in result.text
    assert "RCA finding" in result.text


async def test_escalates_when_confidence_low(make_router, fake_backend) -> None:
    fake_backend.replies = [
        "first attempt\n[CONFIDENCE: 0.30]",
        "deeper attempt\n[CONFIDENCE: 0.85]",
    ]
    router = make_router()

    result = await with_escalation(
        router,
        task_class=TaskClass.RCA,
        system="Diagnose.",
        messages=[{"role": "user", "content": "incident"}],
        threshold=0.65,
    )
    assert len(fake_backend.calls) == 2
    # Second call was the deep tier.
    assert result.tier_used == ModelTier.SONNET
    assert result.escalated is True
    assert "deeper attempt" in result.text
    assert "[CONFIDENCE" not in result.text


async def test_escalates_when_tag_missing(make_router, fake_backend) -> None:
    # No tag at all — treated as confidence=0.0, must escalate.
    fake_backend.replies = ["raw answer no tag", "second answer\n[CONFIDENCE: 0.9]"]
    router = make_router()

    result = await with_escalation(
        router,
        task_class=TaskClass.RCA,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        threshold=0.65,
    )
    assert len(fake_backend.calls) == 2
    assert result.escalated is True
