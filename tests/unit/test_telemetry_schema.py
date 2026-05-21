"""Tests for the universal TelemetryEvent schema."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from apps.ingestion.schema import CanonicalMetric, DeviceType, Severity, TelemetryEvent


@pytest.mark.unit
def test_valid_event_round_trips(telemetry_event_dict: dict) -> None:
    ev = TelemetryEvent.model_validate(telemetry_event_dict)
    payload = ev.model_dump_json()
    assert TelemetryEvent.model_validate_json(payload) == ev


@pytest.mark.unit
def test_canonical_metric_typo_rejected(telemetry_event_dict: dict) -> None:
    telemetry_event_dict["metric"] = "cpu.temperatuer.celsius"   # typo
    with pytest.raises(ValidationError):
        TelemetryEvent.model_validate(telemetry_event_dict)


@pytest.mark.unit
def test_naive_timestamp_rejected(telemetry_event_dict: dict) -> None:
    telemetry_event_dict["timestamp"] = datetime(2026, 1, 1, 12, 0, 0).isoformat()
    with pytest.raises(ValidationError):
        TelemetryEvent.model_validate(telemetry_event_dict)


@pytest.mark.unit
def test_event_is_frozen(telemetry_event_dict: dict) -> None:
    ev = TelemetryEvent.model_validate(telemetry_event_dict)
    with pytest.raises(ValidationError):
        ev.severity = Severity.CRITICAL   # type: ignore[misc]


@pytest.mark.unit
def test_extra_fields_rejected(telemetry_event_dict: dict) -> None:
    telemetry_event_dict["bogus"] = "extra"
    with pytest.raises(ValidationError):
        TelemetryEvent.model_validate(telemetry_event_dict)


@pytest.mark.unit
def test_device_type_enum() -> None:
    assert DeviceType("server") is DeviceType.SERVER
    assert CanonicalMetric("gpu.xid.code") is CanonicalMetric.GPU_XID_CODE
