"""Telemetry ingestion service.

Normalizes raw payloads from Redfish / DCGM / IPMI / SNMP / environmental
sensors into the universal `TelemetryEvent` schema and publishes them on
the Redis event bus. See ARCHITECTURE.md § Data flow.
"""
