"""Central federation orchestrator.

Three modules:
    fleet_view             — aggregates per-site state for the dashboard
    cross_site_correlator  — propagates high-confidence rules across sites
    policy_engine          — gates Executor actions against site/global policy
"""
