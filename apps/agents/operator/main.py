"""Operator — natural-language query agent.

Purpose:
    Translates an operator's natural-language question into a TimescaleDB
    SELECT plus a Plotly chart spec. Pulls runbook snippets from ChromaDB
    (with cross-encoder rerank) for context. Refuses to emit DDL/DML —
    both at the Pydantic schema layer and at the TimescaleStore layer.

Unlike the other agents, Operator is request/response: the FastAPI route
`POST /query` enqueues a request on `query.<request_id>` and awaits the
response.

Topics:
    in:  query.<request_id>  (request-scoped)
    out: query.result
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import QueryResult, Topic
from apps.agents.shared.llm_router import LLMRouter, TaskClass
from apps.agents.shared.quality import CACHE_ENABLED, KG_GROUND_ENABLED
from apps.agents.shared.quality.kg_grounding import (
    format_grounding_errors,
    validate_metrics,
)
from apps.agents.shared.quality.reranker import CrossEncoderReranker
from apps.agents.shared.quality.schemas import OperatorAnswer
from apps.agents.shared.quality.semantic_cache import SemanticCache
from apps.agents.shared.quality.structured import (
    StructuredOutputError,
    call_structured,
)
from apps.agents.shared.ts_client import TimescaleStore
from apps.agents.shared.vector_client import VectorStore

import os

_OPERATOR_SYSTEM = (
    "You are the Operator agent. Translate the user's question into a single "
    "SELECT statement against the TimescaleDB telemetry schema, plus a short "
    "human answer. Use only canonical metric names from the supplied catalog. "
    "Never emit INSERT/UPDATE/DELETE/DDL — output will be rejected if you do."
)


# Retrieval defaults — initial Chroma recall depth + how many runbooks survive rerank.
_RUNBOOK_RECALL_TOP_N = int(os.getenv("OPERATOR_RUNBOOK_RECALL_TOP_N", "20"))
_RUNBOOK_RERANK_TOP_K = int(os.getenv("OPERATOR_RUNBOOK_RERANK_TOP_K", "5"))
_RUNBOOK_COLLECTION = os.getenv("CHROMA_COLLECTION_RUNBOOKS", "dcops_runbooks")


class OperatorAgent(BaseAgent):
    name = "operator"
    subscribed_topic = "query.*"          # request topics; result published to query.result
    event_model = None

    async def on_start(self) -> None:
        await super().on_start()
        self.ts = TimescaleStore.from_env()
        self.vec = VectorStore.from_env()
        await self.ts.connect()
        await self.vec.connect()

        self.cache = SemanticCache(client=self.vec.client)
        self.reranker = CrossEncoderReranker()
        self.llm = LLMRouter(agent_name=self.name, event_bus=self.bus)

        # Resolve the runbooks collection now if Chroma is reachable.
        self.runbooks = await self.vec.get_or_create_collection(_RUNBOOK_COLLECTION)

        self.log.info(
            "operator.ready",
            quality_stack={
                "cache": self.cache.enabled and CACHE_ENABLED,
                "kg_ground": KG_GROUND_ENABLED,
                "reranker_model": self.reranker._model_name,  # noqa: SLF001
                "ts": self.ts.enabled,
                "runbooks": self.runbooks is not None,
            },
        )

    async def on_stop(self) -> None:
        await self.ts.close()
        await self.vec.close()
        await super().on_stop()

    async def handle(self, event: Any) -> None:
        request = self._extract_request(event)
        if request is None:
            self.log.debug("operator.skip", reason="invalid payload")
            return

        question = request["question"]
        request_id = request["request_id"]

        try:
            answer, sources = await self._answer(question)
        except StructuredOutputError as exc:
            self.log.warning("operator.structured_failed", error=str(exc)[:200])
            return

        rows = await self._execute_sql(answer.sql)
        await self._publish_result(
            request_id=request_id,
            question=question,
            answer=answer,
            rows=rows,
            sources=sources,
        )

    # --- pipeline --------------------------------------------------------------

    async def _answer(
        self, question: str
    ) -> tuple[OperatorAnswer, list[dict[str, Any]]]:
        """Structured NL→SQL with retrieval, rerank, and metric grounding.

        Returns the answer plus the runbook sources that fed the prompt (so
        the QueryResult can carry them back to the dashboard for citations).
        """
        cached = await self.cache.get(question)
        if cached is not None:
            try:
                return OperatorAnswer.model_validate_json(cached), []
            except Exception:  # noqa: BLE001
                pass

        sources = await self._retrieve_runbooks(question)
        context = self._build_context(question, sources)
        messages: list[dict[str, Any]] = [{"role": "user", "content": context}]

        answer, _result = await call_structured(
            self.llm,
            schema=OperatorAnswer,
            task_class=TaskClass.NL_TO_SQL,
            system=_OPERATOR_SYSTEM,
            messages=messages,
            max_tokens=1024,
            max_retries=2,
        )

        if KG_GROUND_ENABLED:
            unknown = validate_metrics(answer.referenced_metrics)
            if unknown:
                hint = format_grounding_errors(unknown_metrics=unknown)
                revised, _ = await call_structured(
                    self.llm,
                    schema=OperatorAnswer,
                    task_class=TaskClass.NL_TO_SQL,
                    system=_OPERATOR_SYSTEM,
                    messages=[
                        *messages,
                        {"role": "assistant", "content": answer.model_dump_json()},
                        {"role": "user", "content": hint or ""},
                    ],
                    max_tokens=1024,
                    max_retries=1,
                )
                answer = revised

        if CACHE_ENABLED:
            await self.cache.put(
                question,
                answer.model_dump_json(),
                metadata={"agent": self.name},
            )
        return answer, sources

    async def _retrieve_runbooks(self, question: str) -> list[dict[str, Any]]:
        """Chroma top-N recall → cross-encoder rerank → top-K runbooks.

        Returns a list of `{id, question, sql_template, metrics, category,
        notes, score}` dicts. Empty when the collection is unavailable —
        the agent still works (the LLM just sees a smaller prompt).
        """
        coll = self.runbooks
        if coll is None:
            return []

        try:
            recall = await asyncio.to_thread(
                coll.query,
                query_texts=[question],
                n_results=_RUNBOOK_RECALL_TOP_N,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning("operator.runbook_query_failed", error=str(exc))
            return []

        ids = (recall.get("ids") or [[]])[0]
        docs = (recall.get("documents") or [[]])[0]
        metas = (recall.get("metadatas") or [[]])[0]
        if not docs:
            return []

        # Rerank via cross-encoder. The reranker auto-loads on first use.
        try:
            ranked = await asyncio.to_thread(
                self.reranker.rerank, question, docs, _RUNBOOK_RERANK_TOP_K
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning("operator.rerank_failed", error=str(exc))
            ranked = [(i, 0.0) for i in range(min(len(docs), _RUNBOOK_RERANK_TOP_K))]

        out: list[dict[str, Any]] = []
        for idx, score in ranked:
            if idx >= len(docs):
                continue
            meta = metas[idx] or {}
            out.append(
                {
                    "id": ids[idx] if idx < len(ids) else None,
                    "question": docs[idx],
                    "sql_template": meta.get("sql_template", ""),
                    "metrics": meta.get("metrics", ""),
                    "category": meta.get("category", ""),
                    "notes": meta.get("notes", ""),
                    "score": float(score),
                }
            )
        return out

    async def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        """Run the LLM-emitted SQL through the read-only Timescale path."""
        if not self.ts.enabled:
            return []
        try:
            return await self.ts.execute_select(sql, max_rows=1000)
        except ValueError as exc:
            self.log.warning("operator.sql_rejected", error=str(exc), sql=sql[:200])
            return []

    async def _publish_result(
        self,
        *,
        request_id: UUID,
        question: str,
        answer: OperatorAnswer,
        rows: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> None:
        chart_spec = self._chart_spec(rows, question=question) if rows else None
        # Persist the rows on the QueryResult metadata so the API/dashboard
        # has the raw data in addition to the chart.
        result = QueryResult(
            site_id=self.site_id,
            request_id=request_id,
            question=question,
            answer_text=answer.answer_text,
            sql_executed=answer.sql,
            chart_spec=chart_spec,
            sources=[
                {"id": s["id"], "category": s["category"], "score": s["score"]}
                for s in sources
            ],
            llm_cost_usd=0.0,
            metadata={"rows": _stringify_rows(rows)},
        )
        try:
            await self.bus.publish(Topic.QUERY_RESULT.value, result)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("operator.publish_failed", error=str(exc))

        self.log.info(
            "operator.answer_published",
            request_id=str(request_id),
            metrics=answer.referenced_metrics,
            confidence=answer.confidence,
            rows=len(rows),
            sources=len(sources),
        )

    # --- helpers ---------------------------------------------------------------

    @staticmethod
    def _extract_request(event: Any) -> dict[str, Any] | None:
        """Pull `{question, request_id}` from an incoming bus event."""
        if isinstance(event, dict):
            question = event.get("question")
            if not isinstance(question, str) or not question.strip():
                return None
            rid_raw = event.get("request_id")
            try:
                rid = UUID(str(rid_raw)) if rid_raw else uuid4()
            except (ValueError, TypeError):
                rid = uuid4()
            return {"question": question.strip(), "request_id": rid}
        if isinstance(event, str) and event.strip():
            return {"question": event.strip(), "request_id": uuid4()}
        return None

    @staticmethod
    def _build_context(question: str, sources: list[dict[str, Any]]) -> str:
        """Compose the user-message context — question + canonical metric catalog
        + retrieved runbook exemplars."""
        from apps.ingestion.schema import CanonicalMetric

        catalog = "\n".join(f"  - {m.value}" for m in CanonicalMetric)
        parts = [
            f"Question: {question}",
            "",
            "Canonical metric catalog (use only these names):",
            catalog,
        ]
        if sources:
            parts.append("")
            parts.append("Relevant runbook patterns (use as exemplars, adapt the placeholders):")
            for i, s in enumerate(sources, 1):
                parts.extend(
                    [
                        f"  {i}. {s.get('category')} — {s.get('question')}",
                        f"     SQL: {s.get('sql_template')}",
                        f"     Notes: {s.get('notes')}",
                    ]
                )
        return "\n".join(parts)

    @staticmethod
    def _chart_spec(
        rows: list[dict[str, Any]],
        *,
        question: str | None = None,
    ) -> dict[str, Any] | None:
        """Plotly chart spec from result rows.

        Handles three common shapes:
          - (time, value_num)              → single line
          - (time, <category>, value_num)  → multi-series line (one per category)
          - (<category>, value_num)        → bar chart
          - otherwise                       → None (caller renders as table)
        """
        if not rows:
            return None
        first = rows[0]
        cols = set(first.keys())

        if "time" in cols and "value_num" in cols:
            # Find a non-time, non-value categorical column for multi-series split.
            value_cols = {"value_num"}
            time_cols = {"time"}
            cat_candidates = [
                c for c in cols
                if c not in value_cols and c not in time_cols and isinstance(first.get(c), str)
            ]
            cat_col = cat_candidates[0] if cat_candidates else None
            if cat_col is None:
                return _line_spec(rows, "time", "value_num", question)
            return _multi_line_spec(rows, "time", "value_num", cat_col, question)

        # Bar shape: a categorical key + a numeric value.
        num_cols = [c for c, v in first.items() if isinstance(v, (int, float))]
        cat_cols = [c for c, v in first.items() if isinstance(v, str)]
        if num_cols and cat_cols:
            return _bar_spec(rows, cat_cols[0], num_cols[0], question)

        return None


def _line_spec(
    rows: list[dict[str, Any]],
    x_col: str,
    y_col: str,
    question: str | None,
) -> dict[str, Any]:
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "name": y_col,
                "x": [str(r[x_col]) for r in rows],
                "y": [r[y_col] for r in rows],
            }
        ],
        "layout": _layout(x_col, y_col, question),
    }


def _multi_line_spec(
    rows: list[dict[str, Any]],
    x_col: str,
    y_col: str,
    cat_col: str,
    question: str | None,
) -> dict[str, Any]:
    series: dict[str, dict[str, list[Any]]] = {}
    for r in rows:
        key = str(r.get(cat_col, ""))
        s = series.setdefault(key, {"x": [], "y": []})
        s["x"].append(str(r[x_col]))
        s["y"].append(r[y_col])
    return {
        "data": [
            {"type": "scatter", "mode": "lines", "name": key, "x": s["x"], "y": s["y"]}
            for key, s in series.items()
        ],
        "layout": _layout(x_col, y_col, question),
    }


def _bar_spec(
    rows: list[dict[str, Any]],
    cat_col: str,
    val_col: str,
    question: str | None,
) -> dict[str, Any]:
    return {
        "data": [
            {
                "type": "bar",
                "name": val_col,
                "x": [str(r[cat_col]) for r in rows],
                "y": [r[val_col] for r in rows],
            }
        ],
        "layout": _layout(cat_col, val_col, question),
    }


def _layout(x_title: str, y_title: str, question: str | None) -> dict[str, Any]:
    layout: dict[str, Any] = {
        "xaxis": {"title": x_title},
        "yaxis": {"title": y_title},
    }
    if question:
        layout["title"] = question[:80]
    return layout


def _stringify_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make timestamps + UUIDs JSON-safe so the QueryResult serializes cleanly."""
    out: list[dict[str, Any]] = []
    for r in rows:
        clean = {}
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            else:
                clean[k] = v
        out.append(clean)
    return out


if __name__ == "__main__":
    OperatorAgent.run()
