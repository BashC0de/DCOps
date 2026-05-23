"""Confidence-based tier escalation.

Implements the Haiku → Sonnet (or fast → deep) escalation logic that
[apps/agents/shared/llm_router.py](../llm_router.py) left as a TODO.

Flow:
    1. Run the task on the fast tier; system prompt asks the model to
       end with a `[CONFIDENCE: 0.xx]` tag.
    2. Parse the tag; if confidence < threshold, re-run on the deep tier.
    3. Return whichever result we chose, with `escalated=True` set if
       we used the second call.

Threshold default: `FORENSIC_ESCALATION_THRESHOLD` env var (default 0.65)
mirrors the existing Forensic-specific knob.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from apps.agents.shared.llm_router import LLMResult, LLMRouter, TaskClass

log = get_logger(__name__)


_CONFIDENCE_INSTRUCTION = (
    "\n\nIMPORTANT: End your response with a line of exactly this form: "
    "[CONFIDENCE: 0.NN] where 0.NN is your honest self-assessed confidence "
    "in your answer, from 0.00 (guessing) to 1.00 (certain)."
)

_CONFIDENCE_PATTERN = re.compile(r"\[CONFIDENCE:\s*(-?[0-9]*\.?[0-9]+)\s*\]", re.IGNORECASE)


def parse_confidence(text: str) -> float | None:
    """Pull the `[CONFIDENCE: 0.xx]` tag from a response. None if absent."""
    match = _CONFIDENCE_PATTERN.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return max(0.0, min(1.0, value))


def strip_confidence_tag(text: str) -> str:
    """Remove the `[CONFIDENCE: ...]` tag so callers get clean text."""
    return _CONFIDENCE_PATTERN.sub("", text).strip()


async def with_escalation(
    router: LLMRouter,
    *,
    task_class: TaskClass,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
    threshold: float | None = None,
    temperature: float | None = 0.0,
) -> LLMResult:
    """Run on the fast tier; escalate to deep if self-rated confidence is low.

    Args:
        router: LLMRouter.
        task_class, system, messages, max_tokens, temperature: Forwarded.
        threshold: Confidence cutoff. None = use `FORENSIC_ESCALATION_THRESHOLD`
            env var (default 0.65).

    Returns:
        An LLMResult. If escalation fired, `escalated=True` on the result
        and `text` is from the deep call. The fast-tier response is logged
        but not returned.
    """
    from apps.agents.shared.llm_router import ModelTier  # local to avoid cycle in TYPE_CHECKING

    cutoff = threshold if threshold is not None else float(
        os.getenv("FORENSIC_ESCALATION_THRESHOLD", "0.65")
    )

    annotated_system = system + _CONFIDENCE_INSTRUCTION

    first = await router.call(
        task_class=task_class,
        system=annotated_system,
        messages=messages,
        max_tokens=max_tokens,
        force_tier=ModelTier.HAIKU,
        temperature=temperature,
    )

    confidence = parse_confidence(first.text)
    if confidence is None:
        log.info(
            "quality.escalation.no_confidence_tag",
            note="model did not emit [CONFIDENCE: ...]; assuming low",
        )
        confidence = 0.0

    if confidence >= cutoff:
        # Strip the tag from the returned text so downstream parsers don't see it.
        first.text = strip_confidence_tag(first.text)
        return first

    log.info(
        "quality.escalation.escalating",
        confidence=confidence,
        threshold=cutoff,
    )
    second = await router.call(
        task_class=task_class,
        system=annotated_system,
        messages=messages,
        max_tokens=max_tokens,
        force_tier=ModelTier.SONNET,
        temperature=temperature,
    )
    second.escalated = True
    second.text = strip_confidence_tag(second.text)
    return second


__all__ = ["with_escalation", "parse_confidence", "strip_confidence_tag"]
