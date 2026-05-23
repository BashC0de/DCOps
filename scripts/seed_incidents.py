"""Seed ChromaDB with the synthetic past-incidents corpus.

Idempotent: re-running upserts by `incident.id`, so no duplicates.

Run via `make seed` or directly:
    python scripts/seed_incidents.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Make `apps.*` importable when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402
from scripts._incidents_corpus import CORPUS, PastIncident  # noqa: E402

log = get_logger("seed_incidents")


COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_INCIDENTS", "dcops_incidents")


def to_chroma_payload(corpus: tuple[PastIncident, ...]) -> dict[str, list[Any]]:
    """Map the corpus into Chroma's expected `add`/`upsert` keyword args."""
    return {
        "ids": [p.id for p in corpus],
        "documents": [p.symptoms for p in corpus],
        "metadatas": [
            {
                "root_cause": p.root_cause,
                "resolution": p.resolution,
                "severity": p.severity,
                "kind": p.kind,
            }
            for p in corpus
        ],
    }


def seed(client: Any, *, collection_name: str = COLLECTION_NAME) -> int:
    """Upsert the corpus into Chroma. Returns the number of documents written."""
    payload = to_chroma_payload(CORPUS)
    collection = client.get_or_create_collection(name=collection_name)
    collection.upsert(**payload)
    log.info(
        "seed_incidents.upserted",
        collection=collection_name,
        n=len(payload["ids"]),
    )
    return len(payload["ids"])


def main() -> None:
    configure_logging()
    try:
        import chromadb
    except ImportError as exc:
        log.error("seed_incidents.chromadb_missing", error=str(exc))
        sys.exit(2)

    host = os.getenv("CHROMA_HOST", "localhost")
    port = int(os.getenv("CHROMA_PORT", "8000"))
    log.info("seed_incidents.connect", host=host, port=port)
    client = chromadb.HttpClient(host=host, port=port)
    n = seed(client)
    log.info("seed_incidents.done", n=n)


if __name__ == "__main__":
    main()


__all__ = ["seed", "to_chroma_payload", "COLLECTION_NAME"]
