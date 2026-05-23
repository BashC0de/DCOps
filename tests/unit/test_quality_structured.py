"""Tests for apps/agents/shared/quality/structured.py."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from apps.agents.shared.llm_router import TaskClass
from apps.agents.shared.quality.structured import (
    StructuredOutputError,
    call_structured,
)

pytestmark = pytest.mark.unit


class Verdict(BaseModel):
    severity: str = Field(pattern="^(info|warn|error|critical)$")
    confidence: float = Field(ge=0.0, le=1.0)


async def test_returns_parsed_model_on_clean_json(make_router, fake_backend) -> None:
    fake_backend.replies = ['{"severity": "warn", "confidence": 0.8}']
    router = make_router()

    parsed, result = await call_structured(
        router,
        schema=Verdict,
        task_class=TaskClass.CLASSIFY,
        system="Classify the alert.",
        messages=[{"role": "user", "content": "fan speed spike"}],
    )

    assert isinstance(parsed, Verdict)
    assert parsed.severity == "warn"
    assert parsed.confidence == pytest.approx(0.8)
    assert result.text == fake_backend.replies[0]
    # Schema must be forwarded as response_format on the first call.
    assert isinstance(fake_backend.calls[0]["response_format"], dict)


async def test_strips_code_fences(make_router, fake_backend) -> None:
    fake_backend.replies = ['```json\n{"severity": "error", "confidence": 0.5}\n```']
    router = make_router()

    parsed, _ = await call_structured(
        router,
        schema=Verdict,
        task_class=TaskClass.CLASSIFY,
        system="x",
        messages=[{"role": "user", "content": "x"}],
    )
    assert parsed.severity == "error"


async def test_retries_then_recovers(make_router, fake_backend) -> None:
    fake_backend.replies = [
        "not json at all",
        '{"severity": "critical", "confidence": 0.95}',
    ]
    router = make_router()

    parsed, _ = await call_structured(
        router,
        schema=Verdict,
        task_class=TaskClass.CLASSIFY,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        max_retries=2,
    )
    assert parsed.severity == "critical"
    assert len(fake_backend.calls) == 2
    # The retry message should include the validation error as a correction hint.
    retry_messages = fake_backend.calls[1]["messages"]
    assert any("failed validation" in str(m.get("content", "")) for m in retry_messages)


async def test_raises_after_max_retries(make_router, fake_backend) -> None:
    fake_backend.replies = ["nope", "still nope", "really not json"]
    router = make_router()

    with pytest.raises(StructuredOutputError):
        await call_structured(
            router,
            schema=Verdict,
            task_class=TaskClass.CLASSIFY,
            system="x",
            messages=[{"role": "user", "content": "x"}],
            max_retries=2,
        )
    # 1 initial + 2 retries = 3
    assert len(fake_backend.calls) == 3
