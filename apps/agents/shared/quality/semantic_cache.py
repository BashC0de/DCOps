"""Semantic cache — Chroma-backed prompt cache keyed by embedding similarity.

For repeating prompts (same alert firing across racks; identical NL queries
from the dashboard), this reuses prior LLM responses. The match is by
cosine similarity over an embedding of the prompt; the default threshold
of 0.97 catches near-identical reuses without bleeding into "kind of
similar" prompts.

Storage layout:
    Document = the prompt (Chroma embeds it for similarity search).
    Metadata = `{"response": <text>, ...caller-supplied tags}`.

Memory model:
    - One Chroma collection (`dcops_llm_cache`).
    - Embeddings via Chroma's default sentence-transformers model
      (`all-MiniLM-L6-v2`, ~22M params, ~80MB RAM).
    - LRU-ish: Chroma doesn't auto-evict; production should add a janitor
      that deletes entries older than N days.

Graceful degradation:
    If no Chroma client is passed (e.g. early-week scaffolding without the
    data layer up), the cache becomes a no-op — `get` always returns None,
    `put` is a no-op.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, Any

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from chromadb.api import ClientAPI

log = get_logger(__name__)


class SemanticCache:
    """Chroma-backed near-duplicate cache for LLM responses."""

    def __init__(
        self,
        client: ClientAPI | None = None,
        collection_name: str = "dcops_llm_cache",
        threshold: float = 0.97,
        embedding_fn: Any = None,
    ) -> None:
        """
        Args:
            client: A Chroma client. None disables the cache (all ops no-op).
            collection_name: Chroma collection name.
            threshold: Cosine similarity threshold for a cache hit.
                Higher = stricter; 0.97 catches near-identical prompts only.
            embedding_fn: Optional Chroma `EmbeddingFunction`. If None, lets
                Chroma use its default (sentence-transformers all-MiniLM-L6-v2).
        """
        self._threshold = threshold
        self._collection: Any | None = None
        if client is None:
            return
        try:
            kwargs: dict[str, Any] = {"name": collection_name}
            if embedding_fn is not None:
                kwargs["embedding_function"] = embedding_fn
            self._collection = client.get_or_create_collection(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning("quality.semantic_cache.init_failed", error=str(exc))
            self._collection = None

    @property
    def enabled(self) -> bool:
        return self._collection is not None

    async def get(self, prompt: str) -> str | None:
        """Look up a cached response by semantic similarity to `prompt`."""
        if self._collection is None:
            return None
        try:
            res = self._collection.query(query_texts=[prompt], n_results=1)
        except Exception as exc:  # noqa: BLE001
            log.warning("quality.semantic_cache.query_failed", error=str(exc))
            return None

        distances = res.get("distances") or [[]]
        metadatas = res.get("metadatas") or [[]]
        if not distances or not distances[0] or not metadatas or not metadatas[0]:
            return None

        # Chroma returns cosine *distance* (1 - similarity) by default.
        distance = distances[0][0]
        similarity = 1.0 - float(distance)
        if similarity < self._threshold:
            return None

        meta = metadatas[0][0] or {}
        response = meta.get("response")
        if not isinstance(response, str):
            return None

        log.info(
            "quality.semantic_cache.hit",
            similarity=round(similarity, 4),
            threshold=self._threshold,
        )
        return response

    async def put(
        self,
        prompt: str,
        response: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a (prompt, response) pair for future lookups.

        Idempotent: re-adding the same prompt overwrites the existing entry
        because the ID is derived from the prompt hash.
        """
        if self._collection is None:
            return
        entry_meta = {"response": response, **(metadata or {})}
        try:
            # `upsert` overwrites if the ID exists, avoiding duplicate-add errors.
            self._collection.upsert(
                ids=[_prompt_id(prompt)],
                documents=[prompt],
                metadatas=[entry_meta],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("quality.semantic_cache.put_failed", error=str(exc))


def _prompt_id(prompt: str) -> str:
    """Stable ID for a prompt — first 16 hex chars of its SHA-256."""
    return sha256(prompt.encode("utf-8")).hexdigest()[:16]


__all__ = ["SemanticCache"]
