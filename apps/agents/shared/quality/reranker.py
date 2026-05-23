"""Cross-encoder reranker — local replacement for the Cohere reranker.

Pipeline:
    1. Vector recall (Chroma) returns top-50 candidates.
    2. This reranker scores each (query, candidate) pair with a cross-encoder.
    3. Caller keeps the top-K (typically 3-5) for the LLM context.

Cross-encoders are slower than bi-encoders (they re-score every pair) but
much more precise on relevance. For Operator's runbook retrieval and
Forensic's similar-incident lookup, this is the single biggest knob for
retrieval quality and it costs zero dollars.

Model: `BAAI/bge-reranker-base` — small (~280MB), strong on benchmarks,
permissive license. Override via the `LLM_RERANKER_MODEL` env var.

Memory: the model is loaded lazily on first use and pinned in process.
Roughly 300-400MB resident; calculate this into the agent's memory cap
when reranker is enabled.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


_DEFAULT_MODEL = "BAAI/bge-reranker-base"


class CrossEncoderReranker:
    """Lazy-loading wrapper over sentence-transformers CrossEncoder."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or os.getenv("LLM_RERANKER_MODEL", _DEFAULT_MODEL)
        self._model: object | None = None  # actual type: CrossEncoder

    def _load(self) -> object:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Reranker requires sentence-transformers (already a runtime dep)."
            ) from exc
        log.info("quality.reranker.loading", model=self._model_name)
        self._model = CrossEncoder(self._model_name)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Score (query, candidate) pairs and return the ranked indices.

        Args:
            query: The user/system question.
            candidates: List of candidate texts (e.g. runbook chunks).
            top_k: If given, return only the top-K. None = return all
                candidates ranked.

        Returns:
            List of `(original_index, score)` sorted descending by score.
            Empty input returns empty.
        """
        if not candidates:
            return []
        model = self._load()
        pairs = [(query, c) for c in candidates]
        scores = model.predict(pairs)  # type: ignore[attr-defined]
        ranked = sorted(enumerate(scores), key=lambda kv: float(kv[1]), reverse=True)
        if top_k is not None:
            ranked = ranked[:top_k]
        return [(i, float(s)) for i, s in ranked]


__all__ = ["CrossEncoderReranker"]
