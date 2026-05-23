"""Audit subsystem.

Drains the `audit.events` Redis Stream (populated by every `LLMRouter`
call plus future executor actions) into a durable MinIO archive. Each
payload is content-addressed by SHA-256, so re-publishing an identical
record is idempotent.

Entry point: `apps/audit/main.py` (run as a long-running container under
the `dev`/`demo` profiles).
"""
