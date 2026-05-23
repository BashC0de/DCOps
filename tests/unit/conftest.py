"""Unit-test fixtures shared across quality-layer tests.

Provides:
    fake_backend: A scriptable `Backend` that returns canned responses in
        order, recording each invocation. Drop-in for `LLMRouter(backend=...)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.agents.shared.llm_backends.base import BackendInvocation


@dataclass
class FakeBackend:
    """Scriptable backend for tests. Returns `replies` in order; loops if exhausted."""

    name: str = "fake"
    replies: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    _idx: int = 0

    async def invoke(
        self,
        *,
        model_id: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
        response_format: dict[str, Any] | str | None = None,
    ) -> BackendInvocation:
        self.calls.append(
            {
                "model_id": model_id,
                "system": system,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        if not self.replies:
            text = ""
        else:
            text = self.replies[self._idx % len(self.replies)]
            self._idx += 1
        return BackendInvocation(
            text=text,
            model_id=model_id,
            tokens_in=10,
            tokens_out=20,
            latency_ms=1.0,
            raw={"fake": True},
        )


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def make_router(fake_backend: FakeBackend):
    """Factory: returns a callable that builds a LLMRouter bound to the fake backend."""
    from apps.agents.shared.llm_router import LLMRouter

    def _make(agent_name: str = "test") -> LLMRouter:
        return LLMRouter(agent_name=agent_name, backend=fake_backend)

    return _make
