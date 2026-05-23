"""Tests for apps/agents/shared/quality/verifier.py."""

from __future__ import annotations

import pytest

from apps.agents.shared.llm_router import TaskClass
from apps.agents.shared.quality.verifier import with_verifier

pytestmark = pytest.mark.unit


async def test_returns_generator_output_when_critic_says_ok(make_router, fake_backend) -> None:
    # Reply 0 = generator, reply 1 = critic verdict
    fake_backend.replies = ["My RCA: PSU failure.", "OK"]
    router = make_router()

    result = await with_verifier(
        router,
        task_class=TaskClass.RCA,
        system="Write an RCA.",
        messages=[{"role": "user", "content": "incident"}],
        max_revisions=1,
    )
    assert result.text == "My RCA: PSU failure."
    # Exactly 2 calls: generator + critic.
    assert len(fake_backend.calls) == 2


async def test_revises_when_critic_finds_issues(make_router, fake_backend) -> None:
    # gen #1, critic says issues, gen #2, critic still says issues (max_revisions=1
    # means we stop here and return gen #2 anyway).
    fake_backend.replies = [
        "candidate v1",
        "ISSUES: device id wrong, missing severity",
        "candidate v2",
    ]
    router = make_router()

    result = await with_verifier(
        router,
        task_class=TaskClass.RCA,
        system="Write an RCA.",
        messages=[{"role": "user", "content": "incident"}],
        max_revisions=1,
    )
    # 1 generator + 1 critic + 1 revision = 3 calls.
    assert len(fake_backend.calls) == 3
    assert result.text == "candidate v2"
    # The revision call should include the critic's findings in the messages.
    revise_msgs = fake_backend.calls[2]["messages"]
    flat = " ".join(str(m.get("content", "")) for m in revise_msgs)
    assert "device id wrong" in flat


async def test_accepts_ok_with_punctuation(make_router, fake_backend) -> None:
    fake_backend.replies = ["candidate", "OK."]
    router = make_router()
    result = await with_verifier(
        router,
        task_class=TaskClass.RCA,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        max_revisions=1,
    )
    assert result.text == "candidate"
    assert len(fake_backend.calls) == 2


async def test_critic_called_with_low_temperature(make_router, fake_backend) -> None:
    fake_backend.replies = ["candidate", "OK"]
    router = make_router()
    await with_verifier(
        router,
        task_class=TaskClass.RCA,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        max_revisions=1,
        temperature=0.7,
    )
    # Generator gets the caller's temperature, critic always gets 0.0.
    assert fake_backend.calls[0]["temperature"] == 0.7
    assert fake_backend.calls[1]["temperature"] == 0.0
