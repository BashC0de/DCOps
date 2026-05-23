"""Anthropic backend — original Claude API path.

Kept as an escape valve for users with an API key who want a one-off
quality boost. Not the default. Importing this module requires the
`anthropic` package, which is now an optional extra.
"""

from __future__ import annotations

import os
import time
from typing import Any

from apps.agents.shared.llm_backends.base import BackendInvocation
from apps.agents.shared.logging import get_logger

log = get_logger(__name__)


class AnthropicBackend:
    name = "anthropic"

    def __init__(self) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise RuntimeError(
                "LLM_BACKEND=anthropic requires the 'anthropic' extra. "
                "Install with: uv sync --extra anthropic"
            ) from exc
        self._client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

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
        # Anthropic doesn't have a native JSON-schema response_format flag.
        # The structured.py quality layer enforces schemas at the parser level,
        # which works fine on Anthropic too. We just log a one-off note here.
        if response_format is not None:
            log.debug("anthropic_backend.response_format_ignored", note="enforced at parser layer")

        kwargs: dict[str, Any] = {
            "model": model_id,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        t0 = time.perf_counter()
        response = await self._client.messages.create(**kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        return BackendInvocation(
            text=text,
            model_id=model_id,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            latency_ms=latency_ms,
            raw=response,
        )
