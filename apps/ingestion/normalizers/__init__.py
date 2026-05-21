"""Per-source telemetry normalizers.

Each module exposes an async generator `poll()` that yields TelemetryEvent
records. The shape is identical across sources; that's the whole point.
"""
