"""Self-consistency — fan out N samples and aggregate.

For classification or single-answer tasks, smaller models gain noticeable
accuracy when you sample N times with non-zero temperature and take the
majority vote. For numeric outputs, average instead.

Cost: N× the tokens. Use sparingly — typically for severity classification,
"is this anomalous?", or other high-leverage single-answer calls.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from apps.agents.shared.llm_router import LLMRouter, ModelTier, TaskClass

log = get_logger(__name__)
A = TypeVar("A")


async def vote(
    router: LLMRouter,
    *,
    task_class: TaskClass,
    system: str,
    messages: list[dict[str, Any]],
    n: int = 3,
    temperature: float = 0.7,
    max_tokens: int = 512,
    force_tier: ModelTier | None = None,
    normalize: Callable[[str], A] | None = None,
) -> tuple[A | str, float, list[str]]:
    """Run the same prompt `n` times and return the majority answer.

    Args:
        router: The LLMRouter.
        task_class, system, messages, max_tokens, force_tier: Forwarded.
        n: Number of samples. 3 is the usual sweet spot; 5 for higher-stakes.
        temperature: Sampling temperature (must be > 0 for diversity).
        normalize: Optional callable to coerce each raw text into a comparable
            value (e.g. lowercase, strip, parse-to-enum). Defaults to
            `str.strip` — votes are compared as strings.

    Returns:
        (winning_answer, agreement_ratio, all_normalized_answers).
        `agreement_ratio` is votes_for_winner / n — useful as a confidence
        signal you can feed into the escalation layer.
    """
    norm: Callable[[str], A | str] = normalize or (lambda s: s.strip())  # type: ignore[assignment]

    async def _one() -> str:
        result = await router.call(
            task_class=task_class,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            force_tier=force_tier,
            temperature=temperature,
        )
        return result.text

    raw_samples = await asyncio.gather(*[_one() for _ in range(n)])
    normalized = [norm(s) for s in raw_samples]

    counts = Counter(normalized)
    winner, votes = counts.most_common(1)[0]
    ratio = votes / n
    log.info(
        "quality.self_consistency.vote",
        n=n,
        winner_votes=votes,
        agreement=ratio,
        distinct=len(counts),
    )
    return winner, ratio, [str(x) for x in normalized]


async def average(
    router: LLMRouter,
    *,
    task_class: TaskClass,
    system: str,
    messages: list[dict[str, Any]],
    parser: Callable[[str], float],
    n: int = 3,
    temperature: float = 0.7,
    max_tokens: int = 256,
    force_tier: ModelTier | None = None,
) -> tuple[float, float, list[float]]:
    """Same as `vote`, but for numeric outputs: returns the mean and stddev.

    `parser` extracts a float from each raw response. Failures are dropped;
    a warning is logged. Use stddev as an uncertainty signal.
    """
    async def _one() -> str:
        result = await router.call(
            task_class=task_class,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            force_tier=force_tier,
            temperature=temperature,
        )
        return result.text

    raw_samples = await asyncio.gather(*[_one() for _ in range(n)])
    values: list[float] = []
    for raw in raw_samples:
        try:
            values.append(parser(raw))
        except (ValueError, TypeError):
            log.warning("quality.self_consistency.parse_failed", raw=raw[:120])

    if not values:
        raise RuntimeError("self_consistency.average: no parseable samples")

    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    stddev = var ** 0.5
    return mean, stddev, values


__all__ = ["vote", "average"]
