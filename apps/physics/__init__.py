"""Digital-twin physics engine.

Skeleton entity classes + thermal/power propagation models. Real numerical
implementations land Week 3 (see ROADMAP.md). The simulator and Optimizer
both depend on this module, so the contracts are kept stable from Week 1.
"""

from apps.physics.entities import (
    CRACUnit,
    DataHall,
    Device,
    DeviceState,
    FailureMode,
    GPU,
    PDU,
    Rack,
    Server,
    Switch,
)

__all__ = [
    "CRACUnit",
    "DataHall",
    "Device",
    "DeviceState",
    "FailureMode",
    "GPU",
    "PDU",
    "Rack",
    "Server",
    "Switch",
]
