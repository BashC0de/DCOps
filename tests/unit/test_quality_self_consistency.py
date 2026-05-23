"""Tests for apps/agents/shared/quality/self_consistency.py."""

from __future__ import annotations

import pytest

from apps.agents.shared.llm_router import TaskClass
from apps.agents.shared.quality.self_consistency import average, vote

pytestmark = pytest.mark.unit


async def test_vote_picks_majority(make_router, fake_backend) -> None:
    fake_backend.replies = ["warn", "warn", "error"]
    router = make_router()

    winner, ratio, samples = await vote(
        router,
        task_class=TaskClass.CLASSIFY,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        n=3,
    )

    assert winner == "warn"
    assert ratio == pytest.approx(2 / 3)
    assert sorted(samples) == ["error", "warn", "warn"]


async def test_vote_normalizes_via_callable(make_router, fake_backend) -> None:
    # Same answer but with different casing/whitespace — normalize should collapse.
    fake_backend.replies = ["WARN", " warn ", "  Warn"]
    router = make_router()

    winner, ratio, _ = await vote(
        router,
        task_class=TaskClass.CLASSIFY,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        n=3,
        normalize=lambda s: s.strip().lower(),
    )
    assert winner == "warn"
    assert ratio == 1.0


async def test_vote_temperature_forwarded(make_router, fake_backend) -> None:
    fake_backend.replies = ["a", "a", "b"]
    router = make_router()
    await vote(
        router,
        task_class=TaskClass.CLASSIFY,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        n=3,
        temperature=0.9,
    )
    assert all(c["temperature"] == 0.9 for c in fake_backend.calls)


async def test_average_returns_mean_and_stddev(make_router, fake_backend) -> None:
    fake_backend.replies = ["0.5", "0.7", "0.6"]
    router = make_router()

    mean, stddev, values = await average(
        router,
        task_class=TaskClass.RCA,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        parser=float,
        n=3,
    )
    assert mean == pytest.approx(0.6, abs=1e-6)
    assert stddev > 0
    assert values == [0.5, 0.7, 0.6]


async def test_average_drops_unparseable_samples(make_router, fake_backend) -> None:
    fake_backend.replies = ["0.5", "garbage", "0.7"]
    router = make_router()

    mean, _, values = await average(
        router,
        task_class=TaskClass.RCA,
        system="x",
        messages=[{"role": "user", "content": "x"}],
        parser=float,
        n=3,
    )
    assert mean == pytest.approx(0.6)
    assert values == [0.5, 0.7]
