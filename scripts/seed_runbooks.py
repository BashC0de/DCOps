"""Seed ChromaDB with the synthetic runbooks corpus for Operator agent.

Idempotent: upserts by `runbook.id`, so re-running won't duplicate.

Run via `make seed` or directly:
    python scripts/seed_runbooks.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402
from scripts._runbooks_corpus import CORPUS, Runbook  # noqa: E402

log = get_logger("seed_runbooks")

COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_RUNBOOKS", "dcops_runbooks")


def to_chroma_payload(corpus: tuple[Runbook, ...]) -> dict[str, list[Any]]:
    return {
        "ids": [r.id for r in corpus],
        "documents": [r.question for r in corpus],
        "metadatas": [
            {
                "sql_template": r.sql_template,
                "metrics": ",".join(r.metrics),
                "category": r.category,
                "notes": r.notes,
            }
            for r in corpus
        ],
    }


def seed(client: Any, *, collection_name: str = COLLECTION_NAME) -> int:
    payload = to_chroma_payload(CORPUS)
    collection = client.get_or_create_collection(name=collection_name)
    collection.upsert(**payload)
    log.info("seed_runbooks.upserted", collection=collection_name, n=len(payload["ids"]))
    return len(payload["ids"])


def main() -> None:
    configure_logging()
    try:
        import chromadb
    except ImportError as exc:
        log.error("seed_runbooks.chromadb_missing", error=str(exc))
        sys.exit(2)

    host = os.getenv("CHROMA_HOST", "localhost")
    port = int(os.getenv("CHROMA_PORT", "8000"))
    log.info("seed_runbooks.connect", host=host, port=port)
    client = chromadb.HttpClient(host=host, port=port)
    n = seed(client)
    log.info("seed_runbooks.done", n=n)


if __name__ == "__main__":
    main()


__all__ = ["seed", "to_chroma_payload", "COLLECTION_NAME"]
