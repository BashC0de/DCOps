"""DCOps agents.

Eight agents in two tiers:
    Reasoning: Sentinel, Forensic, Operator, Optimizer, Planner, Vision
    Control:   Action Executor, Rollback Monitor

Agents do not import each other. They communicate via the Redis event bus
(see apps/agents/shared/event_bus.py). Shared utilities live in
apps/agents/shared/.
"""
