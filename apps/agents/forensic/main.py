"""Forensic — automated RCA agent.

Purpose:
    Triggered by `PredictedFailure` events. For each:
      1. Pull a 5-minute telemetry window from TimescaleDB.
      2. Query Neo4j for a 2-hop dependency subgraph.
      3. Retrieve top-K similar past incidents from ChromaDB.
      4. Compose an RCA prompt; route through LLMRouter.
      5. Structured output -> IncidentRCA (schema-constrained).
      6. KG-ground device IDs; revise if any are unknown.
      7. Verifier (critic) pass on the RCA.
      8. Escalation handled inside `quality/escalation.py` callers if needed.
      9. Persist to TimescaleDB + Neo4j; publish `IncidentReport` on the bus.

Topics:
    in:  predictions.failure
    out: incidents.report
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import IncidentReport, PredictedFailure, Topic
from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.llm_router import LLMRouter, TaskClass
from apps.agents.shared.quality import KG_GROUND_ENABLED, VERIFIER_ENABLED
from apps.agents.shared.quality.few_shot import FewShotRetriever
from apps.agents.shared.quality.kg_grounding import format_grounding_errors
from apps.agents.shared.quality.schemas import IncidentRCA
from apps.agents.shared.quality.semantic_cache import SemanticCache
from apps.agents.shared.quality.structured import (
    StructuredOutputError,
    call_structured,
)
from apps.agents.shared.quality.verifier import with_verifier
from apps.agents.shared.ts_client import TimescaleStore
from apps.agents.shared.vector_client import VectorStore

_RCA_SYSTEM = (
    "You are the Forensic agent for a multi-site data center operations platform. "
    "Given a PredictedFailure event and surrounding telemetry context, produce a "
    "root-cause analysis. Be concise. Reference only device IDs and metric names "
    "that appear in the supplied context — do not invent identifiers. Provide "
    "between 1 and 5 ranked hypotheses, each with concrete evidence."
)

_SEVERITY_FROM_CONFIDENCE: list[tuple[float, str]] = [
    (0.9, "critical"),
    (0.7, "error"),
    (0.4, "warn"),
    (0.0, "info"),
]


class ForensicAgent(BaseAgent):
    name = "forensic"
    subscribed_topic = Topic.PREDICTIONS_FAILURE.value
    event_model = PredictedFailure

    async def on_start(self) -> None:
        await super().on_start()
        # Data-layer clients. Each `.connect()` is best-effort; failures
        # leave `enabled=False` and downstream calls become no-ops.
        self.kg = KnowledgeGraph.from_env()
        self.ts = TimescaleStore.from_env()
        self.vec = VectorStore.from_env()
        await self.kg.connect()
        await self.ts.connect()
        await self.vec.connect()

        # Quality components. SemanticCache / FewShotRetriever auto-degrade
        # when client is None.
        self.few_shot = FewShotRetriever(client=self.vec.client)
        self.cache = SemanticCache(client=self.vec.client)

        # Wire the audit-stream + budget-emit channel into the router.
        self.llm = LLMRouter(agent_name=self.name, event_bus=self.bus)

        self.log.info(
            "forensic.ready",
            quality_stack={
                "verifier": VERIFIER_ENABLED,
                "kg_ground": KG_GROUND_ENABLED,
                "few_shot": self.few_shot.enabled,
                "cache": self.cache.enabled,
                "ts": self.ts.enabled,
                "kg": self.kg.enabled,
            },
        )

    async def on_stop(self) -> None:
        await self.kg.close()
        await self.ts.close()
        await self.vec.close()
        await super().on_stop()

    async def handle(self, event: PredictedFailure) -> None:  # type: ignore[override]
        self.log.info(
            "forensic.received",
            device_id=event.device_id,
            failure_kind=event.failure_kind,
            probability=event.probability,
        )
        try:
            rca = await self._analyze(event)
        except StructuredOutputError as exc:
            self.log.warning("forensic.structured_failed", error=str(exc)[:200])
            return

        self.log.info(
            "forensic.rca_produced",
            top_cause=rca.top_hypotheses[0].cause,
            n_hypotheses=len(rca.top_hypotheses),
            confidence=rca.confidence,
        )
        await self._persist_and_publish(event, rca)

    # --- pipeline --------------------------------------------------------------

    async def _analyze(self, event: PredictedFailure) -> IncidentRCA:
        """Run the full quality pipeline. Returns a validated IncidentRCA."""
        context = await self._build_context(event)

        cached = await self.cache.get(context)
        if cached is not None:
            try:
                return IncidentRCA.model_validate_json(cached)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("forensic.cache_invalid", error=str(exc)[:120])

        examples = await self.few_shot.retrieve(context, k=3)
        examples_block = FewShotRetriever.format_as_examples(examples)
        user_prompt = f"{examples_block}\n\nCURRENT INCIDENT:\n{context}"
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]

        rca = await self._call_with_quality(_RCA_SYSTEM, messages)

        if KG_GROUND_ENABLED:
            rca = await self._kg_ground(rca, _RCA_SYSTEM, messages)

        await self.cache.put(
            context,
            rca.model_dump_json(),
            metadata={"agent": self.name, "site_id": self.site_id},
        )
        return rca

    async def _call_with_quality(
        self,
        system: str,
        messages: list[dict[str, Any]],
    ) -> IncidentRCA:
        rca, _result = await call_structured(
            self.llm,
            schema=IncidentRCA,
            task_class=TaskClass.RCA,
            system=system,
            messages=messages,
            max_tokens=2048,
            max_retries=2,
        )
        if not VERIFIER_ENABLED:
            return rca
        verified = await with_verifier(
            self.llm,
            task_class=TaskClass.RCA,
            system=system,
            messages=[
                *messages,
                {"role": "assistant", "content": rca.model_dump_json()},
                {"role": "user", "content": "Review the above RCA. Return a corrected RCA if needed."},
            ],
            max_tokens=2048,
            max_revisions=1,
        )
        try:
            return IncidentRCA.model_validate_json(verified.text)
        except Exception:  # noqa: BLE001
            return rca

    async def _kg_ground(
        self,
        rca: IncidentRCA,
        system: str,
        messages: list[dict[str, Any]],
    ) -> IncidentRCA:
        device_ids = rca.all_device_ids()
        unknown = await self.kg.validate_device_ids(device_ids)
        if not unknown:
            return rca
        hint = format_grounding_errors(unknown_devices=unknown)
        revised_messages = [
            *messages,
            {"role": "assistant", "content": rca.model_dump_json()},
            {"role": "user", "content": hint or ""},
        ]
        try:
            revised, _ = await call_structured(
                self.llm,
                schema=IncidentRCA,
                task_class=TaskClass.RCA,
                system=system,
                messages=revised_messages,
                max_tokens=2048,
                max_retries=1,
            )
            return revised
        except StructuredOutputError:
            self.log.warning("forensic.kg_ground_revise_failed", unknown=unknown)
            return rca

    # --- context build --------------------------------------------------------

    async def _build_context(self, event: PredictedFailure) -> str:
        """Compose the LLM prompt context.

        Includes a 5-minute telemetry window from TimescaleDB and a 2-hop
        dependency subgraph from Neo4j. Both gracefully degrade when their
        respective clients aren't connected.
        """
        telemetry_rows = await self.ts.recent_telemetry(event.device_id, window_s=300, limit=60)
        subgraph = await self.kg.dependency_subgraph(event.device_id, hops=2)

        return (
            f"Site: {event.site_id}\n"
            f"Device: {event.device_id} ({event.device_type})\n"
            f"Predicted failure kind: {event.failure_kind}\n"
            f"Probability: {event.probability:.2f}\n"
            f"Horizon: {event.horizon_hours:.1f}h\n"
            f"Sentinel evidence: {event.evidence}\n\n"
            f"Recent telemetry ({len(telemetry_rows)} samples in last 5 min):\n"
            f"{self._format_telemetry(telemetry_rows)}\n\n"
            f"Dependency neighbors ({len(subgraph)} within 2 hops):\n"
            f"{self._format_subgraph(subgraph)}"
        )

    @staticmethod
    def _format_telemetry(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "  (no telemetry available)"
        out: list[str] = []
        for r in rows[:30]:
            ts = r.get("time")
            metric = r.get("metric", "?")
            value = r.get("value_num")
            if value is None:
                value = r.get("value_str", "")
            unit = r.get("unit") or ""
            out.append(f"  - {ts} {metric}={value}{unit}")
        return "\n".join(out)

    @staticmethod
    def _format_subgraph(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "  (no dependency data available)"
        return "\n".join(
            f"  - {r.get('id')} ({r.get('type')}) "
            f"model={r.get('model')} distance={r.get('distance')}"
            for r in rows[:30]
        )

    # --- persistence + publish ------------------------------------------------

    async def _persist_and_publish(
        self,
        event: PredictedFailure,
        rca: IncidentRCA,
    ) -> None:
        incident_id = uuid4()
        opened_at = datetime.now(timezone.utc)
        severity = self._severity_for(rca.confidence)
        affected = rca.all_device_ids()
        last_result_model = None  # we don't carry the LLMResult into the report yet

        # Best-effort persistence — failures are logged, don't block publish.
        await self.ts.insert_incident(
            incident_id=incident_id,
            opened_at=opened_at,
            site_id=event.site_id,
            severity=severity,
            affected_devices=affected,
            top_hypotheses=[h.model_dump() for h in rca.top_hypotheses],
            confidence=rca.confidence,
            llm_cost_usd=0.0,
            llm_model_used=last_result_model,
            trace_id=event.trace_id,
        )
        await self.kg.register_incident(
            incident_id=str(incident_id),
            opened_at=opened_at.isoformat(),
            severity=severity,
            affected_device_ids=affected,
        )

        report = IncidentReport(
            site_id=event.site_id,
            incident_id=incident_id,
            affected_device_ids=affected,
            top_hypotheses=[h.model_dump() for h in rca.top_hypotheses],
            similar_past_incidents=[],
            confidence=rca.confidence,
            llm_cost_usd=0.0,
            llm_model_used=last_result_model,
            trace_id=event.trace_id,
            parent_event_id=event.event_id,
            metadata={
                "summary": rca.incident_summary,
                "recommended_action": rca.recommended_action,
            },
        )
        try:
            await self.bus.publish(Topic.INCIDENTS_REPORT.value, report)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("forensic.publish_failed", error=str(exc))

    @staticmethod
    def _severity_for(confidence: float) -> str:
        for cutoff, label in _SEVERITY_FROM_CONFIDENCE:
            if confidence >= cutoff:
                return label
        return "info"


if __name__ == "__main__":
    ForensicAgent.run()
