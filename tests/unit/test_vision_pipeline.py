"""Integration test for the Vision agent's quality pipeline."""

from __future__ import annotations

import pytest

from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.llm_router import LLMRouter
from apps.agents.shared.quality.schemas import VisionFinding
from apps.agents.shared.vector_client import VectorStore
from apps.agents.vision.main import VisionAgent
from apps.ingestion.schema import Severity

pytestmark = pytest.mark.unit


def _finding_json(device_id: str = "fra-h1-r07-srv03", confidence: float = 0.85) -> str:
    return VisionFinding(
        finding_summary="amber LED on PSU 2",
        affected_device_ids=[device_id],
        severity=Severity.ERROR,
        confidence=confidence,
        evidence_observations=["amber LED visible on bottom PSU"],
    ).model_dump_json()


@pytest.fixture
def vision_agent(monkeypatch, fake_backend) -> VisionAgent:
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("LLM_QUALITY_VERIFIER", "false")
    monkeypatch.setenv("LLM_QUALITY_KG_GROUND", "false")

    agent = VisionAgent()
    agent.llm = LLMRouter(agent_name=agent.name, backend=fake_backend)

    import apps.agents.vision.main as vm
    monkeypatch.setattr(vm, "VERIFIER_ENABLED", False)
    monkeypatch.setattr(vm, "KG_GROUND_ENABLED", False)

    agent.kg = KnowledgeGraph.from_env()
    agent.vec = VectorStore.from_env()
    from apps.agents.shared.quality.semantic_cache import SemanticCache
    agent.cache = SemanticCache(client=None)
    return agent


async def test_analyze_returns_validated_finding(vision_agent, fake_backend) -> None:
    fake_backend.replies = [_finding_json()]
    request = {
        "context": "rack 7 incident; PSU LED looks off",
        "images": ["base64-image-data-here"],
    }
    finding = await vision_agent._analyze(request)

    assert isinstance(finding, VisionFinding)
    assert finding.severity is Severity.ERROR
    assert finding.affected_device_ids == ["fra-h1-r07-srv03"]
    assert fake_backend.calls[0]["model_id"]
    user_msg = fake_backend.calls[0]["messages"][0]
    assert any(part.get("type") == "image" for part in user_msg["content"])


async def test_extract_request_rejects_payloads_without_context_or_images() -> None:
    assert VisionAgent._extract_request({"foo": "bar"}) is None
    assert VisionAgent._extract_request("not a dict") is None
    assert VisionAgent._extract_request({"context": "x"}) == {"context": "x"}


def test_cache_key_changes_with_images() -> None:
    a = VisionAgent._cache_key({"context": "x", "images": ["aaa"]})
    b = VisionAgent._cache_key({"context": "x", "images": ["bbb"]})
    c = VisionAgent._cache_key({"context": "x", "images": ["aaa"]})
    assert a != b
    assert a == c


def test_cache_key_decodes_base64_when_valid() -> None:
    """Equivalent base64 of the same bytes should yield the same key."""
    from base64 import b64encode
    raw = b"\x00\x01\x02\x03\x04\x05hello"
    standard = b64encode(raw).decode()
    a = VisionAgent._cache_key({"context": "x", "images": [standard]})
    b = VisionAgent._cache_key({"context": "x", "images": [standard]})
    assert a == b
    # Different image bytes => different key.
    different = b64encode(b"different bytes").decode()
    c = VisionAgent._cache_key({"context": "x", "images": [different]})
    assert a != c
