"""In-repo mock vendor endpoints for ingestion normalizers.

A single FastAPI service emulates the four real-world telemetry sources
the normalizers target — Redfish (Dell iDRAC), NVIDIA DCGM exporter, SNMP
(switches/PDUs), IPMI, and facility env sensors. This is faster and more
reproducible than wrangling four separate vendor-specific Docker images.

Endpoints live in `apps.mocks.main`. The service is brought up via the
`mocks` compose profile.
"""
