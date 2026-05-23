"""Verifier — generator + critic loop.

Standard quality-recovery trick: a small model is often better at finding
errors in a candidate answer than at producing the answer from scratch.
We exploit this by:

    1. Generator runs the task and produces a candidate.
    2. Critic is given the candidate and prompted to find errors.
    3. If the critic reports issues, the generator revises.

This catches a lot of "almost right" failure modes — wrong device referenced,
self-contradicting reasoning, missing required field — that smaller models
hit more often than Sonnet would.

The critic uses the same router; pass `critic_tier=ModelTier.HAIKU` to keep
it cheap. For high-stakes calls, run the critic on the deep tier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from apps.agents.shared.llm_router import LLMResult, LLMRouter, ModelTier, TaskClass

log = get_logger(__name__)


_DEFAULT_CRITIC_SYSTEM = (
    "You are a strict reviewer. The user will show you a TASK and a CANDIDATE "
    "answer. Find errors, missing info, or contradictions in the candidate. "
    "Reply with one of:\n"
    "  OK — if the candidate is correct and complete.\n"
    "  ISSUES: <comma-separated list of concrete problems> — otherwise.\n"
    "Be terse. Do not rewrite the answer."
)


async def with_verifier(
    router: LLMRouter,
    *,
    task_class: TaskClass,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
    force_tier: ModelTier | None = None,
    critic_tier: ModelTier | None = None,
    critic_system: str | None = None,
    max_revisions: int = 1,
    temperature: float | None = 0.0,
) -> LLMResult:
    """Generate → critique → revise. Returns the final accepted result.

    Args:
        router: LLMRouter.
        task_class, system, messages, max_tokens, force_tier: Forwarded to
            the generator call.
        critic_tier: Tier for the critic. Defaults to the same tier as the
            generator (cheap). Pass HAIKU explicitly to force fast critic.
        critic_system: Override the default critic system prompt.
        max_revisions: How many times to revise on critic objections.
            Total LLM calls = 1 + 2*max_revisions (critic + revision).
        temperature: Generator temperature. Critic is always 0.0.

    Returns:
        The LLMResult from the final (accepted or last-attempted) generator
        call. The critic's findings are logged but not part of the return
        value; callers read them through structured logs.
    """
    from apps.agents.shared.llm_router import TaskClass as TC

    critic_sys = critic_system or _DEFAULT_CRITIC_SYSTEM

    result = await router.call(
        task_class=task_class,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
        force_tier=force_tier,
        temperature=temperature,
    )

    for revision in range(max_revisions):
        critic_messages = [
            {
                "role": "user",
                "content": (
                    "TASK:\n"
                    + system
                    + "\n\nCONTEXT:\n"
                    + _stringify_messages(messages)
                    + "\n\nCANDIDATE:\n"
                    + result.text
                ),
            }
        ]
        critique = await router.call(
            task_class=TC.CLASSIFY,
            system=critic_sys,
            messages=critic_messages,
            max_tokens=256,
            force_tier=critic_tier,
            temperature=0.0,
        )

        verdict = critique.text.strip()
        if _critic_accepts(verdict):
            log.info(
                "quality.verifier.accepted",
                revision=revision,
                verdict_prefix=verdict[:80],
            )
            return result

        log.info(
            "quality.verifier.issues",
            revision=revision,
            verdict_prefix=verdict[:200],
        )
        # Revision: ask the generator to fix using the critic's findings.
        revision_messages = [
            *messages,
            {"role": "assistant", "content": result.text},
            {
                "role": "user",
                "content": (
                    "A reviewer flagged these issues with your answer:\n"
                    f"{verdict}\n\n"
                    "Provide a corrected answer that addresses each issue."
                ),
            },
        ]
        result = await router.call(
            task_class=task_class,
            system=system,
            messages=revision_messages,
            max_tokens=max_tokens,
            force_tier=force_tier,
            temperature=temperature,
        )

    return result


def _critic_accepts(verdict: str) -> bool:
    """Did the critic say OK?"""
    head = verdict.strip().split()[0].upper().rstrip(":,.") if verdict.strip() else ""
    return head == "OK"


def _stringify_messages(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            # multimodal content — flatten text parts
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


__all__ = ["with_verifier"]
