"""Quality layers on top of the LLM router.

These modules compensate for smaller OSS models being weaker than Sonnet on
hard reasoning. They are opt-in helpers; agents call them instead of (or
around) `LLMRouter.call` directly. Each is independently usable.

Modules:
    structured       — JSON-schema-constrained decoding + Pydantic validation
    self_consistency — N-sample voting / averaging
    verifier         — generator + critic loop
    kg_grounding     — validate LLM outputs against Neo4j + CanonicalMetric
    semantic_cache   — Chroma-backed cache keyed by prompt embedding
    few_shot         — retrieve top-K past incidents as exemplars
    reranker         — local cross-encoder rerank (replaces Cohere)
    escalation       — re-run on the deep tier when confidence is low

Env flags (all default-on except cache, which auto-disables without Chroma):
    LLM_QUALITY_SELF_CONSISTENCY_N
    LLM_QUALITY_VERIFIER
    LLM_QUALITY_KG_GROUND
    LLM_QUALITY_CACHE

See ARCHITECTURE.md § LLM routing strategy for context.
"""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Public env-driven defaults consumed by the helpers below.
SELF_CONSISTENCY_N = _env_int("LLM_QUALITY_SELF_CONSISTENCY_N", 3)
VERIFIER_ENABLED = _env_bool("LLM_QUALITY_VERIFIER", True)
KG_GROUND_ENABLED = _env_bool("LLM_QUALITY_KG_GROUND", True)
CACHE_ENABLED = _env_bool("LLM_QUALITY_CACHE", True)


__all__ = [
    "SELF_CONSISTENCY_N",
    "VERIFIER_ENABLED",
    "KG_GROUND_ENABLED",
    "CACHE_ENABLED",
]
