"""Tests for the runbook-retrieval + rerank step in Operator's pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.agents.operator.main import OperatorAgent
from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.llm_router import LLMRouter
from apps.agents.shared.quality.schemas import OperatorAnswer
from apps.agents.shared.ts_client import TimescaleStore
from apps.agents.shared.vector_client import VectorStore

pytestmark = pytest.mark.unit


def _answer_json() -> str:
    return OperatorAnswer(
        answer_text="ok",
        sql="SELECT 1",
        referenced_metrics=["cpu.temp.celsius"],
        confidence=0.8,
    ).model_dump_json()


@dataclass
class _FakeCollection:
    """Returns a fixed list of documents from `query`."""

    docs: list[str] = field(default_factory=list)
    metas: list[dict[str, Any]] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def query(self, *, query_texts: list[str], n_results: int) -> dict[str, Any]:
        self.calls.append({"query_texts": query_texts, "n_results": n_results})
        # Truncate to n_results to match Chroma's behavior.
        n = min(n_results, len(self.docs))
        return {
            "ids":       [self.ids[:n]],
            "documents": [self.docs[:n]],
            "metadatas": [self.metas[:n]],
        }


@dataclass
class _FakeReranker:
    """Returns indices in reverse order so we can verify the agent uses the ranking."""

    calls: list[tuple[str, list[str], int | None]] = field(default_factory=list)

    def rerank(self, query: str, candidates: list[str], top_k: int | None = None):  # noqa: ANN001, ANN201
        self.calls.append((query, candidates, top_k))
        # Reverse-rank so order is observable.
        n = len(candidates) if top_k is None else min(top_k, len(candidates))
        return [(i, float(n - i)) for i in range(n)][::-1]


@pytest.fixture
def operator_agent(monkeypatch, fake_backend):
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("LLM_QUALITY_KG_GROUND", "false")
    monkeypatch.setenv("LLM_QUALITY_CACHE", "false")
    agent = OperatorAgent()
    agent.llm = LLMRouter(agent_name=agent.name, backend=fake_backend)
    import apps.agents.operator.main as om
    monkeypatch.setattr(om, "KG_GROUND_ENABLED", False)
    monkeypatch.setattr(om, "CACHE_ENABLED", False)
    agent.ts = TimescaleStore.from_env()
    agent.vec = VectorStore.from_env()
    from apps.agents.shared.quality.semantic_cache import SemanticCache
    agent.cache = SemanticCache(client=None)
    agent.reranker = _FakeReranker()
    return agent


async def test_runbook_retrieval_uses_chroma_and_reranker(operator_agent, fake_backend) -> None:
    fake_backend.replies = [_answer_json()]
    coll = _FakeCollection(
        docs=["q1", "q2", "q3"],
        metas=[{"category": "thermal", "sql_template": "SELECT 1", "notes": "n1"},
               {"category": "gpu",     "sql_template": "SELECT 2", "notes": "n2"},
               {"category": "power",   "sql_template": "SELECT 3", "notes": "n3"}],
        ids=["rb-1", "rb-2", "rb-3"],
    )
    operator_agent.runbooks = coll

    sources = await operator_agent._retrieve_runbooks("how hot are racks?")

    # Both retrieval (Chroma) and rerank were exercised.
    assert coll.calls, "expected a Chroma query"
    assert operator_agent.reranker.calls, "expected a rerank call"
    # Sources have the metadata pulled through.
    assert sources
    assert all("sql_template" in s for s in sources)
    assert all("score" in s for s in sources)


async def test_retrieve_returns_empty_when_collection_missing(operator_agent) -> None:
    operator_agent.runbooks = None
    out = await operator_agent._retrieve_runbooks("anything")
    assert out == []


async def test_build_context_includes_runbook_exemplars() -> None:
    sources = [
        {
            "id": "rb-thermal-001",
            "question": "Which racks ran the hottest?",
            "sql_template": "SELECT rack_id, MAX(value_num)...",
            "metrics": "env.outlet.celsius",
            "category": "thermal",
            "notes": "Per-rack peak temp.",
            "score": 2.5,
        }
    ]
    ctx = OperatorAgent._build_context("hot racks?", sources)
    assert "runbook patterns" in ctx
    assert "rb-thermal-001" not in ctx  # we don't include the id, just the content
    assert "thermal" in ctx
    assert "Which racks ran the hottest?" in ctx
    assert "SELECT rack_id" in ctx


async def test_build_context_without_sources_is_brief() -> None:
    ctx = OperatorAgent._build_context("hot racks?", [])
    assert "runbook patterns" not in ctx
    assert "Question: hot racks?" in ctx


async def test_full_answer_threads_sources_through(operator_agent, fake_backend) -> None:
    fake_backend.replies = [_answer_json()]
    operator_agent.runbooks = _FakeCollection(
        docs=["q1"], metas=[{"category": "thermal", "sql_template": "SELECT 1", "notes": "n"}], ids=["rb-1"]
    )
    answer, sources = await operator_agent._answer("question")
    assert isinstance(answer, OperatorAnswer)
    assert len(sources) == 1
    # The prompt should have included the runbook content as an exemplar.
    user_prompt = fake_backend.calls[0]["messages"][0]["content"]
    assert "runbook patterns" in user_prompt
