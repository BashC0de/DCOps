"""LLM routing with cost tracking and escalation.

Purpose:
    Single chokepoint for every LLM call made anywhere in the platform.
    Routes routine work to Haiku, escalates complex / low-confidence work
    to Sonnet, enforces per-agent daily USD budgets, and logs every call
    to the audit trail.

Ships: Week 5 (full implementation alongside Forensic). Skeleton is
ready earlier so other agents can import the contract.

See ARCHITECTURE.md § LLM routing strategy for the decision flow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from apps.agents.shared.logging import get_logger

log = get_logger(__name__)


# --- Model tier definitions ------------------------------------------------------

class ModelTier(StrEnum):
    HAIKU = "haiku"
    SONNET = "sonnet"


# Per-model USD/1M-token pricing. Update when Anthropic changes rates.
# Source: anthropic.com/pricing
PRICING: dict[ModelTier, dict[str, float]] = {
    ModelTier.HAIKU:  {"input_per_mtok": 1.00, "output_per_mtok": 5.00},
    ModelTier.SONNET: {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
}


def _model_id(tier: ModelTier) -> str:
    """Resolve a tier to a concrete model ID from env (defaults baked in)."""
    if tier is ModelTier.HAIKU:
        return os.getenv("ANTHROPIC_MODEL_HAIKU", "claude-haiku-4-5-20251001")
    return os.getenv("ANTHROPIC_MODEL_SONNET", "claude-sonnet-4-6")


# --- Task classes ---------------------------------------------------------------

class TaskClass(StrEnum):
    """Declared by the calling agent. The router uses this to pick a default tier."""

    CLASSIFY = "classify"                    # Haiku
    EXPLAIN = "explain"                      # Haiku
    SUMMARIZE = "summarize"                  # Haiku
    NL_TO_SQL = "nl_to_sql"                  # Haiku
    RCA = "rca"                              # Haiku, escalate to Sonnet on low confidence
    MULTIMODAL = "multimodal"                # Sonnet (vision)
    DEEP_REASONING = "deep_reasoning"        # Sonnet


DEFAULT_TIER: dict[TaskClass, ModelTier] = {
    TaskClass.CLASSIFY: ModelTier.HAIKU,
    TaskClass.EXPLAIN: ModelTier.HAIKU,
    TaskClass.SUMMARIZE: ModelTier.HAIKU,
    TaskClass.NL_TO_SQL: ModelTier.HAIKU,
    TaskClass.RCA: ModelTier.HAIKU,
    TaskClass.MULTIMODAL: ModelTier.SONNET,
    TaskClass.DEEP_REASONING: ModelTier.SONNET,
}


# --- Response models -------------------------------------------------------------

@dataclass
class LLMResult:
    """What the router returns to the caller."""

    text: str
    model_used: str
    tier_used: ModelTier
    tokens_in: int
    tokens_out: int
    usd_cost: float
    escalated: bool
    raw: Any                              # full provider response object, for inspection


class CallRecord(BaseModel):
    """Persisted audit record for a single LLM call."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent: str
    task_class: TaskClass
    tier_used: ModelTier
    model_id: str
    tokens_in: int
    tokens_out: int
    usd_cost: float
    escalated: bool
    request_id: str | None = None


# --- Router ---------------------------------------------------------------------

class LLMRouter:
    """Decides which model to call, tracks cost, enforces per-agent budgets."""

    def __init__(self, agent_name: str, daily_budget_usd: float | None = None) -> None:
        self.agent_name = agent_name
        self.daily_budget = daily_budget_usd or float(
            os.getenv("LLM_DAILY_BUDGET_USD", "5.00")
        )
        self._spent_today_usd: float = 0.0
        self._last_reset_date: str = self._today()
        self._client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _reset_if_new_day(self) -> None:
        today = self._today()
        if today != self._last_reset_date:
            self._spent_today_usd = 0.0
            self._last_reset_date = today

    @staticmethod
    def _compute_cost(tier: ModelTier, tokens_in: int, tokens_out: int) -> float:
        p = PRICING[tier]
        return (tokens_in * p["input_per_mtok"] + tokens_out * p["output_per_mtok"]) / 1_000_000

    async def call(
        self,
        *,
        task_class: TaskClass,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        force_tier: ModelTier | None = None,
        escalate_threshold: float | None = None,
        self_rate_confidence: bool = False,
    ) -> LLMResult:
        """Route and execute an LLM call.

        Args:
            task_class: What kind of task this is. Used to pick the default tier.
            system: System prompt.
            messages: Anthropic-shaped messages list.
            max_tokens: Output cap.
            force_tier: Skip tier selection logic; use this tier directly.
            escalate_threshold: If the first call self-rates confidence < this,
                re-run on Sonnet. Only meaningful when `self_rate_confidence=True`.
            self_rate_confidence: TODO(week-5). When True, the prompt should
                instruct the model to emit a JSON `{"confidence": float}` and
                the router parses it for escalation decisions.

        Returns:
            LLMResult with token counts, USD cost, and which tier was used.
        """
        self._reset_if_new_day()
        if self._spent_today_usd >= self.daily_budget:
            log.warning(
                "llm_router.budget_exceeded",
                agent=self.agent_name,
                spent=self._spent_today_usd,
                budget=self.daily_budget,
            )
            # TODO(week-5): downgrade to Haiku and emit `budget.exceeded` event.

        tier = force_tier or DEFAULT_TIER[task_class]
        escalated = False

        result = await self._invoke(tier, system, messages, max_tokens)

        # TODO(week-5): parse confidence from result.text when self_rate_confidence=True
        # and re-invoke on Sonnet if below escalate_threshold.
        _ = escalate_threshold
        _ = self_rate_confidence

        record = CallRecord(
            agent=self.agent_name,
            task_class=task_class,
            tier_used=result.tier_used,
            model_id=result.model_used,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            usd_cost=result.usd_cost,
            escalated=escalated,
        )
        self._spent_today_usd += result.usd_cost
        log.info("llm_router.call", **record.model_dump(mode="json"))
        # TODO(week-3): publish CallRecord to `audit.events` stream.
        return result

    async def _invoke(
        self,
        tier: ModelTier,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResult:
        model_id = _model_id(tier)
        response = await self._client.messages.create(
            model=model_id,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        cost = self._compute_cost(tier, tokens_in, tokens_out)
        return LLMResult(
            text=text,
            model_used=model_id,
            tier_used=tier,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usd_cost=cost,
            escalated=False,
            raw=response,
        )


__all__ = ["LLMRouter", "LLMResult", "ModelTier", "TaskClass", "CallRecord"]
