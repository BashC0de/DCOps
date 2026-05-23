"""Structured output — JSON-schema-constrained decoding.

Wraps `LLMRouter.call` so that the model returns JSON conforming to a
Pydantic schema. On parse failure, retries with the validation error
fed back as a correction hint.

Why this matters with smaller OSS models:
    A 3B/7B model is much more likely than Sonnet to drift into prose
    or emit subtly malformed JSON. Schema-constrained decoding (Ollama
    0.5+ native via the `format` field) bounds the output grammar at
    decode time, eliminating a whole class of "the model returned
    prose, can't parse it" bugs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from apps.agents.shared.llm_router import LLMResult, LLMRouter, ModelTier, TaskClass

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Raised when the model can't produce schema-valid JSON after retries."""

    def __init__(self, last_text: str, last_error: ValidationError) -> None:
        super().__init__(f"structured output failed after retries: {last_error}")
        self.last_text = last_text
        self.last_error = last_error


async def call_structured(
    router: LLMRouter,
    *,
    schema: type[T],
    task_class: TaskClass,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
    max_retries: int = 2,
    force_tier: ModelTier | None = None,
    temperature: float | None = 0.0,
) -> tuple[T, LLMResult]:
    """Run an LLM call constrained to return JSON matching `schema`.

    Args:
        router: An `LLMRouter` instance.
        schema: A Pydantic model class. Its JSON Schema is sent to the
            backend (if supported) and the response is validated against it.
        task_class: Forwarded to the router for tier selection.
        system: System prompt.
        messages: Anthropic-shaped messages.
        max_tokens: Output cap.
        max_retries: Number of correction-loop attempts on validation failure.
        force_tier: Optional tier override.
        temperature: Defaults to 0.0 for determinism.

    Returns:
        (parsed_model, final_llm_result). `final_llm_result` is the LLMResult
        from the call that produced the accepted JSON — useful for the audit
        log (model used, tokens, latency).

    Raises:
        StructuredOutputError: If all retries fail validation.
    """
    json_schema = schema.model_json_schema()
    schema_hint = (
        "\n\nReturn ONLY a single JSON object matching this schema. "
        "Do not include prose, code fences, or explanation:\n"
        + json.dumps(json_schema, indent=2)
    )
    working_messages = list(messages)
    last_text = ""
    last_err: ValidationError | None = None

    for attempt in range(max_retries + 1):
        result = await router.call(
            task_class=task_class,
            system=system + schema_hint,
            messages=working_messages,
            max_tokens=max_tokens,
            force_tier=force_tier,
            temperature=temperature,
            response_format=json_schema,
        )
        last_text = result.text
        try:
            parsed = schema.model_validate_json(_extract_json(result.text))
            if attempt > 0:
                log.info(
                    "quality.structured.recovered",
                    schema=schema.__name__,
                    attempts=attempt + 1,
                )
            return parsed, result
        except (ValidationError, json.JSONDecodeError) as exc:
            last_err = exc if isinstance(exc, ValidationError) else None
            log.warning(
                "quality.structured.parse_failed",
                schema=schema.__name__,
                attempt=attempt + 1,
                error=str(exc)[:200],
            )
            if attempt == max_retries:
                break
            working_messages = [
                *working_messages,
                {"role": "assistant", "content": result.text},
                {
                    "role": "user",
                    "content": (
                        f"That response failed validation:\n{exc}\n\n"
                        "Return a corrected JSON object matching the schema exactly."
                    ),
                },
            ]

    raise StructuredOutputError(last_text, last_err or ValidationError.from_exception_data("", []))


def _extract_json(text: str) -> str:
    """Best-effort: strip code fences and isolate the outermost JSON object."""
    s = text.strip()
    if s.startswith("```"):
        # ```json ... ``` or ``` ... ```
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    # Find outermost { ... } if there's surrounding noise.
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start : end + 1]
    return s


__all__ = ["call_structured", "StructuredOutputError"]
