"""Operator — natural-language query agent.

Purpose:
    Translates an operator's natural-language question into a TimescaleDB
    SELECT plus a Plotly chart spec. Pulls runbook snippets from ChromaDB
    for context. Refuses to emit DDL/DML.

Ships: Week 6 (see ROADMAP.md).

Unlike the other agents, Operator is request/response: the FastAPI route
`POST /query` enqueues a request on `query.<request_id>` and awaits the
response. Operator does not run a continuous bus subscription loop.

Topics:
    in:  query.<request_id>  (request-scoped)
    out: query.result
"""

from __future__ import annotations

from typing import Any

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import Topic
from apps.agents.shared.llm_router import LLMRouter


class OperatorAgent(BaseAgent):
    name = "operator"
    subscribed_topic = "query.*"          # request topics; result published to query.result
    event_model = None

    async def on_start(self) -> None:
        await super().on_start()
        self.llm = LLMRouter(agent_name=self.name)
        # TODO(week-6): connect to TimescaleDB (read-only role) and ChromaDB.
        self.log.info("operator.ready", note="skeleton — NL→SQL pipeline ships Week 6")

    async def handle(self, event: Any) -> None:
        # TODO(week-6): parse question, retrieve runbook chunks, call LLM,
        #               validate SQL is SELECT-only, execute, build Plotly spec,
        #               publish QueryResult to Topic.QUERY_RESULT.
        self.log.debug("operator.tick", payload=event)
        _ = Topic.QUERY_RESULT            # silence unused-import warning until Week 6


if __name__ == "__main__":
    OperatorAgent.run()
