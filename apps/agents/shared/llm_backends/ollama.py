"""Ollama backend — local OSS models via the Ollama HTTP API.

Talks to Ollama over plain HTTP (no extra SDK). The host defaults to
`OLLAMA_HOST` env var or `http://ollama:11434` (the docker-compose service).

Token counts come from Ollama's `prompt_eval_count` / `eval_count`. USD cost
is always zero — the router treats Ollama as a free tier.

Multimodal: when a message contains `images` (a list of base64 strings),
this backend passes them through; the chosen model must support vision
(e.g. `qwen2-vl:7b`, `llava:7b`).

Structured output: `response_format="json"` enables JSON mode;
`response_format={...schema...}` passes the JSON Schema directly to Ollama
0.5+ for grammar-constrained decoding.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from apps.agents.shared.llm_backends.base import BackendInvocation

# Long timeout — first-call cold-loads pull the model weights into RAM.
_DEFAULT_TIMEOUT_S = 300.0


class OllamaBackend:
    name = "ollama"

    def __init__(self, host: str | None = None, timeout_s: float | None = None) -> None:
        self._host = (host or os.getenv("OLLAMA_HOST", "http://ollama:11434")).rstrip("/")
        self._timeout_s = timeout_s or float(os.getenv("OLLAMA_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
        # Keep-alive: how long Ollama keeps a model loaded after the last call.
        # "-1" = forever (use for the always-resident small model).
        self._default_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
        self._client = httpx.AsyncClient(base_url=self._host, timeout=self._timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

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
        options: dict[str, Any] = {"num_predict": max_tokens}
        if temperature is not None:
            options["temperature"] = temperature

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "keep_alive": self._default_keep_alive,
            "options": options,
        }
        if response_format is not None:
            # Ollama accepts either the literal string "json" or a JSON Schema dict.
            payload["format"] = response_format

        t0 = time.perf_counter()
        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        latency_ms = (time.perf_counter() - t0) * 1000.0

        # Ollama returns: {message: {role, content}, prompt_eval_count, eval_count, ...}
        message = data.get("message", {})
        text = message.get("content", "") if isinstance(message, dict) else ""
        tokens_in = int(data.get("prompt_eval_count", 0))
        tokens_out = int(data.get("eval_count", 0))

        return BackendInvocation(
            text=text,
            model_id=model_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            raw=data,
        )
