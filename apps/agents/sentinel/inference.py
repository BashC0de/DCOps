"""XGBoost-based predictive scoring with a graceful model-missing fallback.

Loads a trained classifier from `SENTINEL_MODEL_PATH` (default
`data/models/sentinel.xgb`). When the file is absent — which is the
default state until the training pipeline has run — `enabled` is False
and `predict_proba` returns 0.0; Sentinel still ships rules-only
predictions in that mode.

The model is trained by `scripts/train_sentinel.py` to predict
`failure_within_24h` from the feature vector defined in
`apps/agents/sentinel/features.py::feature_columns()`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from apps.agents.sentinel.features import feature_columns, feature_vector
from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    import xgboost as xgb  # noqa: F401

log = get_logger(__name__)


DEFAULT_MODEL_PATH = "data/models/sentinel.xgb"


class SentinelModel:
    """Lazy-loading wrapper around an XGBoost classifier."""

    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path or os.getenv("SENTINEL_MODEL_PATH", DEFAULT_MODEL_PATH)
        self._booster: object | None = None  # actual type: xgb.Booster
        self._feature_columns: list[str] = feature_columns()

    def load(self) -> bool:
        """Try to load the model file. Returns True if loaded."""
        if self._booster is not None:
            return True
        if not os.path.exists(self._model_path):
            log.info(
                "sentinel.model_missing",
                path=self._model_path,
                note="running in rules-only mode until training has produced a model",
            )
            return False
        try:
            import xgboost as xgb
            booster = xgb.Booster()
            booster.load_model(self._model_path)
            self._booster = booster
            log.info("sentinel.model_loaded", path=self._model_path)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("sentinel.model_load_failed", path=self._model_path, error=str(exc))
            return False

    @property
    def enabled(self) -> bool:
        return self._booster is not None

    def predict_proba(self, features: dict[str, float]) -> float:
        """Return predicted probability of failure-within-horizon. 0.0 when disabled."""
        if self._booster is None:
            return 0.0
        try:
            import numpy as np
            import xgboost as xgb
            vec = np.array([feature_vector(features)], dtype=float)
            dmat = xgb.DMatrix(vec, feature_names=self._feature_columns)
            proba = float(self._booster.predict(dmat)[0])
            # Clamp for safety — pad against models that emit logits instead of sigmoid.
            return max(0.0, min(1.0, proba))
        except Exception as exc:  # noqa: BLE001
            log.warning("sentinel.predict_failed", error=str(exc))
            return 0.0


__all__ = ["SentinelModel", "DEFAULT_MODEL_PATH"]
