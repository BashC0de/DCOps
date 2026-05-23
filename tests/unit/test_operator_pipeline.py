"""Integration test for the Operator agent's quality pipeline."""

from __future__ import annotations

import pytest

from apps.agents.operator.main import OperatorAgent
from apps.agents.shared.llm_router import LLMRouter
from apps.agents.shared.quality.schemas import OperatorAnswer
from apps.agents.shared.ts_client import TimescaleStore
from apps.agents.shared.vector_client import VectorStore

pytestmark = pytest.mark.unit


def _answer_json(
    *,
    sql: str = "SELECT value FROM telemetry WHERE metric = 'cpu.temp.celsius'",
    metrics: list[str] | None = None,
) -> str:
    return OperatorAnswer(
        answer_text="here it is",
        sql=sql,
        referenced_metrics=metrics or ["cpu.temp.celsius"],
        confidence=0.85,
    ).model_dump_json()


@pytest.fixture
def operator_agent(monkeypatch, fake_backend) -> OperatorAgent:
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
    from apps.agents.shared.quality.reranker import CrossEncoderReranker
    from apps.agents.shared.quality.semantic_cache import SemanticCache
    agent.cache = SemanticCache(client=None)
    agent.reranker = CrossEncoderReranker()
    agent.runbooks = None  # no chroma collection in unit tests
    return agent


async def test_answer_returns_parsed_select(operator_agent, fake_backend) -> None:
    fake_backend.replies = [_answer_json()]
    answer, sources = await operator_agent._answer("how hot is rack 7?")

    assert isinstance(answer, OperatorAnswer)
    assert answer.sql.upper().startswith("SELECT")
    assert answer.referenced_metrics == ["cpu.temp.celsius"]
    assert sources == []  # no runbooks collection in this fixture


async def test_answer_rejects_and_retries_on_insert_attempt(
    operator_agent, fake_backend
) -> None:
    bad_payload = (
        '{"answer_text": "x", "sql": "INSERT INTO telemetry VALUES (1)",'
        ' "referenced_metrics": [], "confidence": 0.5}'
    )
    fake_backend.replies = [bad_payload, _answer_json()]

    answer, _sources = await operator_agent._answer("show me data")
    assert answer.sql.upper().startswith("SELECT")
    assert len(fake_backend.calls) == 2


async def test_unknown_metric_triggers_revise(
    operator_agent, fake_backend, monkeypatch
) -> None:
    import apps.agents.operator.main as om
    monkeypatch.setattr(om, "KG_GROUND_ENABLED", True)

    fake_backend.replies = [
        _answer_json(metrics=["gpu.fake.metric"]),
        _answer_json(metrics=["gpu.temp.celsius"]),
    ]
    answer, _sources = await operator_agent._answer("show me hot gpus")
    assert answer.referenced_metrics == ["gpu.temp.celsius"]
    assert len(fake_backend.calls) == 2
    last_msgs = fake_backend.calls[1]["messages"]
    flat = " ".join(str(m.get("content", "")) for m in last_msgs)
    assert "gpu.fake.metric" in flat


def test_extract_request_handles_dict_and_string() -> None:
    out = OperatorAgent._extract_request({"question": "hello"})
    assert out is not None and out["question"] == "hello"
    out = OperatorAgent._extract_request("hello")
    assert out is not None and out["question"] == "hello"
    assert OperatorAgent._extract_request({"other": "x"}) is None
    assert OperatorAgent._extract_request(None) is None
    assert OperatorAgent._extract_request("") is None


def test_extract_request_preserves_request_id_when_uuid() -> None:
    from uuid import uuid4
    rid = uuid4()
    out = OperatorAgent._extract_request({"question": "x", "request_id": str(rid)})
    assert out is not None and out["request_id"] == rid


def test_extract_request_generates_uuid_when_missing() -> None:
    out = OperatorAgent._extract_request({"question": "x"})
    assert out is not None
    # New UUID; just verify it's the right type and not zero.
    from uuid import UUID
    assert isinstance(out["request_id"], UUID)


async def test_execute_sql_no_op_when_ts_disabled(operator_agent) -> None:
    rows = await operator_agent._execute_sql("SELECT 1")
    assert rows == []


def test_chart_spec_handles_empty_returns_none() -> None:
    # Detailed shape coverage lives in tests/unit/test_operator_chart_spec.py.
    # Here we just confirm the original empty / single-row time-series cases.
    assert OperatorAgent._chart_spec([]) is None
    spec = OperatorAgent._chart_spec(
        [{"time": "2026-05-22T10:00:00Z", "value_num": 42.5}]
    )
    assert spec is not None
    assert spec["data"][0]["type"] == "scatter"
    assert spec["data"][0]["y"] == [42.5]
