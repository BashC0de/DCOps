"""Tests for apps/agents/shared/quality/kg_grounding.py."""

from __future__ import annotations

import pytest

from apps.agents.shared.quality.kg_grounding import (
    KGValidator,
    format_grounding_errors,
    validate_metrics,
)

pytestmark = pytest.mark.unit


def test_validate_metrics_accepts_canonical() -> None:
    bad = validate_metrics(["cpu.temp.celsius", "gpu.power.watts"])
    assert bad == []


def test_validate_metrics_flags_unknown() -> None:
    bad = validate_metrics(["cpu.temp.celsius", "gpu.fake.metric", "made.up"])
    assert sorted(bad) == ["gpu.fake.metric", "made.up"]


async def test_kg_validator_no_op_without_kg() -> None:
    v = KGValidator(kg=None)
    assert v.enabled is False
    assert await v.validate_device_ids(["x", "y"]) == []
    assert await v.validate_site_ids(["frankfurt"]) == []


async def test_kg_validator_delegates_to_kg() -> None:
    class _Fake:
        enabled = True
        async def validate_device_ids(self, ids):  # noqa: ANN001, ANN201
            return [i for i in ids if i.startswith("bad-")]
        async def validate_site_ids(self, ids):  # noqa: ANN001, ANN201
            return []

    v = KGValidator(kg=_Fake())
    assert v.enabled is True
    assert await v.validate_device_ids(["bad-1", "good-1"]) == ["bad-1"]
    assert await v.validate_site_ids(["frankfurt"]) == []


def test_format_grounding_errors_none_when_empty() -> None:
    assert format_grounding_errors() is None
    assert format_grounding_errors(unknown_metrics=[]) is None


def test_format_grounding_errors_renders_lists() -> None:
    msg = format_grounding_errors(
        unknown_metrics=["foo.bar"],
        unknown_devices=["srv-999"],
    )
    assert msg is not None
    assert "foo.bar" in msg
    assert "srv-999" in msg
    assert "knowledge graph" in msg
