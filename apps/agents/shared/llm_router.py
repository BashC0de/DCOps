"""LLM routing with cost tracking, escalation, and pluggable backends.

Purpose:
    Single chokepoint for every LLM call made anywhere in the platform.
    Picks a model based on `TaskClass` + `ModelTier`, enforces per-agent
    daily budgets (USD on paid backends), publishes a `CallRecord` to the
    `audit.events` Redis stream, and on budget breach downgrades to the
    fast tier + emits a `budget.exceeded` event.

Backends:
    - `ollama` (default) — local OSS models via Ollama HTTP API. Free.
    - `anthropic` — Claude API. Pay-per-token. Optional extra.

Selected via `LLM_BACKEND` env var. See `apps/agents/shared/llm_backends/`.

Confidence-based escalation lives in `apps/agents/shared/quality/escalation.py`;
this module no longer carries that responsibility.

See ARCHITECTURE.md § LLM routing strategy for the decision flow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from apps.agents.shared.events import BudgetExceeded
from apps.agents.shared.llm_backends import Backend, get_backend
from apps.agents.shared.logging import get_logger

log = get_logger(__name__)


# --- Bus-like protocol -----------------------------------------------------------

class _BusLike(Protocol):
    """Structural type for the subset of EventBus the router needs.

    Kept as a protocol so unit tests can pass a minimal fake without
    constructing a real Redis client. The agent's `self.bus` satisfies it.
    """

    async def publish(self, topic: str, event: BaseModel) -> int: ...
    async def publish_stream(
        self,
        stream_key: str,
        event: BaseModel,
        maxlen: int | None = ...,
    ) -> str: ...


# --- Model tier definitions ------------------------------------------------------

class ModelTier(StrEnum):
    """Abstract capability tier. Maps to a concrete model per backend.

    Names kept as HAIKU/SONNET for back-compat with existing call sites,
    but they're now just labels for 'fast' and 'deep' on any backend.
    """

    HAIKU = "haiku"    # fast, small, cheap
    SONNET = "sonnet"  # deeper reasoning, slower


# --- Task classes ---------------------------------------------------------------

class TaskClass(StrEnum):
    """Declared by the calling agent. The router uses this to pick a default tier."""

    CLASSIFY = "classify"                    # fast tier
    EXPLAIN = "explain"                      # fast tier
    SUMMARIZE = "summarize"                  # fast tier
    NL_TO_SQL = "nl_to_sql"                  # fast tier (coder model on Ollama)
    RCA = "rca"                              # fast tier, escalate to deep on low confidence
    MULTIMODAL = "multimodal"                # vision model
    DEEP_REASONING = "deep_reasoning"        # deep tier


DEFAULT_TIER: dict[TaskClass, ModelTier] = {
    TaskClass.CLASSIFY: ModelTier.HAIKU,
    TaskClass.EXPLAIN: ModelTier.HAIKU,
    TaskClass.SUMMARIZE: ModelTier.HAIKU,
    TaskClass.NL_TO_SQL: ModelTier.HAIKU,
    TaskClass.RCA: ModelTier.HAIKU,
    TaskClass.MULTIMODAL: ModelTier.SONNET,
    TaskClass.DEEP_REASONING: ModelTier.SONNET,
}


# --- Model resolution -----------------------------------------------------------

# Per-backend USD/1M-token pricing. Ollama is free. Anthropic pricing from
# anthropic.com/pricing — update when rates change.
_ANTHROPIC_PRICING: dict[ModelTier, dict[str, float]] = {
    ModelTier.HAIKU:  {"input_per_mtok": 1.00, "output_per_mtok": 5.00},
    ModelTier.SONNET: {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
}


def _resolve_model_id(backend_name: str, tier: ModelTier, task: TaskClass) -> str:
    """Pick a concrete model ID from env, given the active backend + tier + task."""
    if backend_name == "anthropic":
        if tier is ModelTier.HAIKU:
            return os.getenv("ANTHROPIC_MODEL_HAIKU", "claude-haiku-4-5-20251001")
        return os.getenv("ANTHROPIC_MODEL_SONNET", "claude-sonnet-4-6")

    # Ollama (and any future local backend) — pick by task first, then tier.
    if task is TaskClass.MULTIMODAL:
        return os.getenv("LLM_MODEL_VISION", "qwen2-vl:7b")
    if task is TaskClass.NL_TO_SQL:
        return os.getenv("LLM_MODEL_CODER", "qwen2.5-coder:3b")
    if tier is ModelTier.HAIKU:
        return os.getenv("LLM_MODEL_FAST", "llama3.2:3b")
    # SONNET tier for non-vision, non-coder work: reasoning model.
    # DEEP_REASONING uses the heavier "deep" model when explicitly forced.
    if task is TaskClass.DEEP_REASONING:
        return os.getenv("LLM_MODEL_DEEP", "deepseek-r1:8b")
    return os.getenv("LLM_MODEL_REASONING", "qwen2.5:7b")


# --- Response models -------------------------------------------------------------

@dataclass
class LLMResult:
    """What the router returns to the caller."""

    text: str
    model_used: str
    tier_used: ModelTier
    tokens_in: int
    tokens_out: int
    usd_cost: float       # 0.0 on local backends
    latency_ms: float
    escalated: bool
    downgraded: bool      # True if budget breach forced a tier downgrade
    raw: Any              # full provider response object, for inspection


class CallRecord(BaseModel):
    """Persisted audit record for a single LLM call.

    Streamed to `audit.events` via Redis Streams. See ARCHITECTURE.md §
    Explainability and audit.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent: str
    backend: str
    task_class: TaskClass
    tier_used: ModelTier
    model_id: str
    tokens_in: int
    tokens_out: int
    usd_cost: float
    latency_ms: float
    escalated: bool
    downgraded: bool = False
    request_id: str | None = None


# --- Router ---------------------------------------------------------------------

class LLMRouter:
    """Decides which model to call, tracks cost/latency, enforces budgets."""

    AUDIT_STREAM = "audit.events"
    BUDGET_TOPIC = "alerts.budget_exceeded"

    def __init__(
        self,
        agent_name: str,
        daily_budget_usd: float | None = None,
        backend: Backend | None = None,
        event_bus: _BusLike | None = None,
    ) -> None:
        self.agent_name = agent_name
        # Note: explicit `is None` — `or` would treat 0.0 (valid value) as falsy.
        self.daily_budget = (
            daily_budget_usd
            if daily_budget_usd is not None
            else float(os.getenv("LLM_DAILY_BUDGET_USD", "5.00"))
        )
        self._spent_today_usd: float = 0.0
        self._last_reset_date: str = self._today()
        self._backend: Backend = backend or get_backend()
        self._bus: _BusLike | None = event_bus
        # One-shot guard so we only emit `budget.exceeded` once per day.
        self._budget_exceeded_emitted: bool = False

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _reset_if_new_day(self) -> None:
        today = self._today()
        if today != self._last_reset_date:
            self._spent_today_usd = 0.0
            self._last_reset_date = today
            self._budget_exceeded_emitted = False

    @staticmethod
    def _compute_cost(backend_name: str, tier: ModelTier, tokens_in: int, tokens_out: int) -> float:
        if backend_name != "anthropic":
            return 0.0
        p = _ANTHROPIC_PRICING[tier]
        return (tokens_in * p["input_per_mtok"] + tokens_out * p["output_per_mtok"]) / 1_000_000

    async def call(
        self,
        *,
        task_class: TaskClass,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        force_tier: ModelTier | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | str | None = None,
    ) -> LLMResult:
        """Route and execute an LLM call.

        Args:
            task_class: What kind of task this is. Used to pick the default tier.
            system: System prompt.
            messages: Anthropic-shaped messages list. Ollama backend accepts the
                same shape; an optional `images: [b64, ...]` key per message is
                honored for multimodal models.
            max_tokens: Output cap.
            force_tier: Skip tier selection logic; use this tier directly.
                Honored unless the daily budget has been exceeded on a paid
                backend, in which case the call is downgraded to fast tier.
            temperature: Sampling temperature. None = backend default.
            response_format: `"json"` for JSON mode; a dict for JSON-Schema-
                constrained decoding (Ollama 0.5+ native).

        Returns:
            LLMResult with token counts, USD cost, latency, and which tier
            was used. `downgraded=True` when a budget breach forced fast tier.

        Note:
            Confidence-based escalation is provided by
            `apps.agents.shared.quality.escalation.with_escalation`, not by
            this method. Keep call sites narrow.
        """
        self._reset_if_new_day()

        requested_tier = force_tier or DEFAULT_TIER[task_class]
        tier, downgraded = await self._apply_budget_policy(requested_tier)

        result = await self._invoke(
            tier, task_class, system, messages, max_tokens, temperature, response_format
        )
        result.downgraded = downgraded

        await self._record_and_audit(task_class, result, downgraded)
        return result

    async def _apply_budget_policy(
        self, requested_tier: ModelTier
    ) -> tuple[ModelTier, bool]:
        """Return (effective_tier, downgraded). Emits budget.exceeded once per day."""
        if self._backend.name != "anthropic":
            return requested_tier, False
        if self._spent_today_usd < self.daily_budget:
            return requested_tier, False

        # Over budget on Anthropic — force fast tier.
        log.warning(
            "llm_router.budget_exceeded",
            agent=self.agent_name,
            spent=self._spent_today_usd,
            budget=self.daily_budget,
        )
        if not self._budget_exceeded_emitted and self._bus is not None:
            site_id = os.getenv("SITE_ID", "unknown")
            try:
                await self._bus.publish(
                    self.BUDGET_TOPIC,
                    BudgetExceeded(
                        site_id=site_id,
                        agent=self.agent_name,
                        spent_usd=self._spent_today_usd,
                        budget_usd=self.daily_budget,
                        backend=self._backend.name,
                    ),
                )
                self._budget_exceeded_emitted = True
            except Exception as exc:  # noqa: BLE001
                log.warning("llm_router.budget_emit_failed", error=str(exc))
        return ModelTier.HAIKU, True

    async def _record_and_audit(
        self,
        task_class: TaskClass,
        result: LLMResult,
        downgraded: bool,
    ) -> None:
        record = CallRecord(
            agent=self.agent_name,
            backend=self._backend.name,
            task_class=task_class,
            tier_used=result.tier_used,
            model_id=result.model_used,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            usd_cost=result.usd_cost,
            latency_ms=result.latency_ms,
            escalated=result.escalated,
            downgraded=downgraded,
        )
        self._spent_today_usd += result.usd_cost
        log.info("llm_router.call", **record.model_dump(mode="json"))
        if self._bus is not None:
            try:
                await self._bus.publish_stream(self.AUDIT_STREAM, record)
            except Exception as exc:  # noqa: BLE001 — audit failures must not break the call
                log.warning("llm_router.audit_publish_failed", error=str(exc))

    async def _invoke(
        self,
        tier: ModelTier,
        task_class: TaskClass,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
        response_format: dict[str, Any] | str | None = None,
    ) -> LLMResult:
        model_id = _resolve_model_id(self._backend.name, tier, task_class)
        invocation = await self._backend.invoke(
            model_id=model_id,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        cost = self._compute_cost(
            self._backend.name, tier, invocation.tokens_in, invocation.tokens_out
        )
        return LLMResult(
            text=invocation.text,
            model_used=invocation.model_id,
            tier_used=tier,
            tokens_in=invocation.tokens_in,
            tokens_out=invocation.tokens_out,
            usd_cost=cost,
            latency_ms=invocation.latency_ms,
            escalated=False,
            downgraded=False,
            raw=invocation.raw,
        )


__all__ = ["LLMRouter", "LLMResult", "ModelTier", "TaskClass", "CallRecord"]
