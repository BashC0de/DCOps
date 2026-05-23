"""Few-shot retrieval — pull top-K past incidents as exemplars.

For Forensic RCA, retrieving 3-5 similar past incidents and including their
{symptoms, root_cause, resolution} triples in the prompt turns the task from
"reason about this from scratch" into "pattern-match against known cases."
Small OSS models gain a *lot* of accuracy from this — often more than from
upgrading the model.

Usage:
    retriever = FewShotRetriever(chroma_client, collection="dcops_incidents")
    examples = await retriever.retrieve(query=symptoms_summary, k=3)
    prompt = retriever.format_as_examples(examples) + actual_question
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from chromadb.api import ClientAPI

log = get_logger(__name__)


class FewShotRetriever:
    """Top-K similar-incident retrieval from a Chroma collection.

    Each stored document should carry metadata fields that the formatter can
    render — at minimum `root_cause` and `resolution`. The Forensic agent
    writes these when it closes an incident (Week 5+).
    """

    def __init__(
        self,
        client: ClientAPI | None = None,
        collection_name: str = "dcops_incidents",
    ) -> None:
        self._collection: Any | None = None
        if client is None:
            return
        try:
            self._collection = client.get_or_create_collection(name=collection_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("quality.few_shot.init_failed", error=str(exc))
            self._collection = None

    @property
    def enabled(self) -> bool:
        return self._collection is not None

    async def retrieve(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        """Return up to `k` past incidents most similar to `query`.

        Each entry is `{document: str, metadata: dict, distance: float}`.
        Returns [] when the collection is unavailable or empty.
        """
        if self._collection is None:
            return []
        try:
            res = self._collection.query(query_texts=[query], n_results=k)
        except Exception as exc:  # noqa: BLE001
            log.warning("quality.few_shot.query_failed", error=str(exc))
            return []

        documents = (res.get("documents") or [[]])[0]
        metadatas = (res.get("metadatas") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]

        out: list[dict[str, Any]] = []
        for doc, meta, dist in zip(documents, metadatas, distances, strict=False):
            out.append(
                {
                    "document": doc,
                    "metadata": meta or {},
                    "distance": float(dist),
                }
            )
        return out

    @staticmethod
    def format_as_examples(examples: list[dict[str, Any]]) -> str:
        """Render retrieved incidents as an `EXAMPLES` block for the prompt."""
        if not examples:
            return ""
        lines = ["EXAMPLES — past incidents similar to the current one:", ""]
        for i, ex in enumerate(examples, start=1):
            meta = ex.get("metadata") or {}
            symptoms = ex.get("document", "")
            cause = meta.get("root_cause", "(unknown)")
            resolution = meta.get("resolution", "(unknown)")
            lines.append(f"Example {i}:")
            lines.append(f"  Symptoms: {symptoms}")
            lines.append(f"  Root cause: {cause}")
            lines.append(f"  Resolution: {resolution}")
            lines.append("")
        return "\n".join(lines)


__all__ = ["FewShotRetriever"]
