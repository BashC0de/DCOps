"""Natural-language query endpoint. Proxies to Operator agent. Ships: Week 6."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    site: str | None = None


@router.post("")
async def nl_query(req: QueryRequest) -> dict[str, object]:
    """Forward to Operator agent and await its `QueryResult`. Skeleton until Week 6."""
    # TODO(week-6): publish to `query.{request_id}`, await result on `query.result`,
    #               return parsed QueryResult.
    return {
        "request_id": str(uuid4()),
        "question": req.question,
        "answer_text": "Operator agent not yet wired (Week 6).",
        "sql_executed": None,
        "chart_spec": None,
        "sources": [],
    }
