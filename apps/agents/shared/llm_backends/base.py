"""Backend protocol — what every LLM provider must implement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class BackendInvocation:
    """Raw provider response, normalized."""

    text: str
    model_id: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    raw: Any


class Backend(Protocol):
    """Minimal contract for a chat-completions provider."""

    name: str

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
        """Run one completion.

        Args:
            temperature: Sampling temperature. None = backend default.
            response_format: Constrains output. `"json"` requests JSON-mode;
                a dict is treated as a JSON Schema (Ollama 0.5+ native;
                Anthropic ignored with a warning). None = freeform text.
        """
        ...
