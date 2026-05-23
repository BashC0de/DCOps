"""Integration test for the Forensic agent's quality pipeline.

Exercises `_analyze()` end-to-end against a FakeBackend so the full chain
(structured output -> verifier -> KG ground) is covered without needing
Ollama, Redis, Neo4j, or Chroma to be running.
"""

from __future__ import annotations

import pytest

from apps.agents.forensic.main import ForensicAgent
from apps.agents.shared.events import PredictedFailure
from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.llm_router import LLMRouter
from apps.agents.shared.quality.schemas import IncidentRCA, RCAHypothesis
from apps.agents.shared.ts_client import TimescaleStore
from apps.agents.shared.vector_client import VectorStore

pytestmark = pytest.mark.unit


def _rca_json(device_id: str, confidence: float = 0.9) -> str:
    return IncidentRCA(
        incident_summary="GPU thermal event",
        top_hypotheses=[
            RCAHypothesis(
                cause="CRAC drift",
                probability=0.7,
                evidence_summary="inlet temps climbing",
                affected_device_ids=[device_id],
            ),
        ],
        confidence=confidence,
        recommended_action="bump CRAC fans to 90%",
    ).model_dump_json()


@pytest.fixture
def forensic_agent(monkeypatch, fake_backend) -> ForensicAgent:
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("LLM_QUALITY_VERIFIER", "false")
    monkeypatch.setenv("LLM_QUALITY_KG_GROUND", "false")

    agent = ForensicAgent()
    agent.llm = LLMRouter(agent_name=agent.name, backend=fake_backend)

    # Patch the quality-flag globals captured at import time.
    import apps.agents.forensic.main as fm
    monkeypatch.setattr(fm, "VERIFIER_ENABLED", False)
    monkeypatch.setattr(fm, "KG_GROUND_ENABLED", False)

    # Unconnected clients are graceful-degrading no-ops (driver/pool/client=None).
    agent.kg = KnowledgeGraph.from_env()
    agent.ts = TimescaleStore.from_env()
    agent.vec = VectorStore.from_env()

    # Quality components wired to nothing.
    from apps.agents.shared.quality.few_shot import FewShotRetriever
    from apps.agents.shared.quality.semantic_cache import SemanticCache
    agent.few_shot = FewShotRetriever(client=None)
    agent.cache = SemanticCache(client=None)
    return agent


def _event(device_id: str = "fra-h1-r07-srv03") -> PredictedFailure:
    return PredictedFailure(
        site_id="frankfurt",
        device_id=device_id,
        device_type="gpu",
        failure_kind="gpu_ecc_runaway",
        probability=0.85,
        horizon_hours=2.0,
        evidence={"ecc_count_last_5min": 47},
    )


async def test_analyze_returns_validated_rca(forensic_agent, fake_backend) -> None:
    fake_backend.replies = [_rca_json("fra-h1-r07-srv03", confidence=0.9)]

    rca = await forensic_agent._analyze(_event())

    assert isinstance(rca, IncidentRCA)
    assert rca.top_hypotheses[0].affected_device_ids == ["fra-h1-r07-srv03"]
    assert rca.confidence == pytest.approx(0.9)
    assert isinstance(fake_backend.calls[0]["response_format"], dict)


async def test_analyze_retries_on_malformed_json(forensic_agent, fake_backend) -> None:
    fake_backend.replies = [
        "not json at all",
        _rca_json("fra-h1-r07-srv03"),
    ]
    rca = await forensic_agent._analyze(_event())
    assert isinstance(rca, IncidentRCA)
    assert len(fake_backend.calls) == 2


async def test_kg_grounding_revises_unknown_devices(
    forensic_agent, fake_backend, monkeypatch
) -> None:
    import apps.agents.forensic.main as fm
    monkeypatch.setattr(fm, "KG_GROUND_ENABLED", True)

    class _FakeKG:
        enabled = True
        async def validate_device_ids(self, ids):  # noqa: ANN001, ANN201
            return [i for i in ids if i.startswith("HALLU-")]
        async def dependency_subgraph(self, device_id, hops=2):  # noqa: ANN001, ANN201
            return []
        async def validate_site_ids(self, ids):  # noqa: ANN001, ANN201
            return []

    forensic_agent.kg = _FakeKG()

    fake_backend.replies = [
        _rca_json("HALLU-001", confidence=0.9),
        _rca_json("fra-h1-r07-srv03", 0.9),
    ]
    rca = await forensic_agent._analyze(_event())
    assert "HALLU-001" not in rca.all_device_ids()
    assert len(fake_backend.calls) == 2
    last_msg = fake_backend.calls[1]["messages"][-1]
    assert "do not exist" in last_msg["content"]


def test_severity_for_confidence() -> None:
    assert ForensicAgent._severity_for(0.95) == "critical"
    assert ForensicAgent._severity_for(0.75) == "error"
    assert ForensicAgent._severity_for(0.5) == "warn"
    assert ForensicAgent._severity_for(0.1) == "info"
