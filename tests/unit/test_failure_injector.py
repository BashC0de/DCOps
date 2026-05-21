"""Tests for the physics failure injector."""

from __future__ import annotations

import pytest

from apps.physics.entities import DeviceState, FailureMode
from apps.physics.failure_injector import clear, inject
from apps.simulator.devices import build_halls
from apps.simulator.sites import get_site


@pytest.mark.unit
def test_inject_gpu_ecc_runaway_marks_device_failing() -> None:
    site = get_site("frankfurt")
    halls = build_halls(site)
    hall = halls[0]

    gpu = next(
        d for rack in hall.racks for d in rack.devices if d.type == "gpu"
    )
    pre_ecc = getattr(gpu, "ecc_correctable_count", 0)

    result = inject(hall, gpu.id, FailureMode.GPU_ECC_RUNAWAY)
    assert result.state == DeviceState.FAILING
    assert result.failure_mode == FailureMode.GPU_ECC_RUNAWAY
    assert getattr(result, "ecc_correctable_count") > pre_ecc


@pytest.mark.unit
def test_clear_resets_state() -> None:
    site = get_site("frankfurt")
    halls = build_halls(site)
    hall = halls[0]
    gpu = next(d for rack in hall.racks for d in rack.devices if d.type == "gpu")

    inject(hall, gpu.id, FailureMode.GPU_ECC_RUNAWAY)
    cleared = clear(hall, gpu.id)
    assert cleared.state == DeviceState.HEALTHY
    assert cleared.failure_mode == FailureMode.NONE


@pytest.mark.unit
def test_unknown_device_raises() -> None:
    site = get_site("frankfurt")
    halls = build_halls(site)
    with pytest.raises(LookupError):
        inject(halls[0], "no-such-device", FailureMode.GPU_ECC_RUNAWAY)
