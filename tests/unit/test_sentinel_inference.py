"""Tests for sentinel.inference — model-missing fallback only.

A real XGBoost predict test would need a trained .xgb file; we cover
that via integration. Here we assert the wrapper degrades gracefully
when the model file isn't present.
"""

from __future__ import annotations

import math

import pytest

from apps.agents.sentinel.features import feature_columns
from apps.agents.sentinel.inference import SentinelModel

pytestmark = pytest.mark.unit


def test_model_missing_path_does_not_load() -> None:
    m = SentinelModel(model_path="/tmp/this-file-does-not-exist.xgb")
    assert m.load() is False
    assert m.enabled is False


def test_predict_returns_zero_when_disabled() -> None:
    m = SentinelModel(model_path="/tmp/this-file-does-not-exist.xgb")
    m.load()
    feats = {c: math.nan for c in feature_columns()}
    proba = m.predict_proba(feats)
    assert proba == 0.0
