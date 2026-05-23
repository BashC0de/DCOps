"""LLM provider backends.

The router in `llm_router.py` is provider-agnostic; concrete provider calls
live here. Each backend implements the `Backend` protocol.

Selected at runtime via the `LLM_BACKEND` env var (default: `ollama`).
"""

from __future__ import annotations

import os

from apps.agents.shared.llm_backends.base import Backend, BackendInvocation


def get_backend(name: str | None = None) -> Backend:
    """Resolve the active backend by name. Defaults to `LLM_BACKEND` env var."""
    chosen = (name or os.getenv("LLM_BACKEND", "ollama")).lower()
    if chosen == "ollama":
        from apps.agents.shared.llm_backends.ollama import OllamaBackend
        return OllamaBackend()
    if chosen == "anthropic":
        from apps.agents.shared.llm_backends.anthropic import AnthropicBackend
        return AnthropicBackend()
    raise ValueError(f"Unknown LLM_BACKEND={chosen!r} (expected 'ollama' or 'anthropic')")


__all__ = ["Backend", "BackendInvocation", "get_backend"]
