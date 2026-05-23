"""FastAPI application entry point.

Purpose:
    HTTP + WebSocket API for the Next.js dashboard. Endpoint groups:
      /telemetry  — recent telemetry by site / device / metric
      /incidents  — incident timeline + per-incident detail + audit lineage
      /agents     — agent health + recent decisions
      /twin       — current physical/thermal state for the digital twin
      /query      — proxy to Operator agent
      /ws         — WebSocket for live incident push

The shared TimescaleDB + Neo4j clients are constructed once in the
lifespan and exposed via `app.state.ts` / `app.state.kg`. Routes pull
them via FastAPI's `Request.app.state` rather than module globals so
tests can swap in fakes.

Run locally: `uvicorn apps.api.main:app --reload --port 8080`
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.agents.shared.event_bus import EventBus
from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.logging import configure_logging, get_logger
from apps.agents.shared.ts_client import TimescaleStore
from apps.api.routes import (
    agents,
    federation,
    fleet,
    forecasts,
    incidents,
    query,
    recommendations,
    telemetry,
    twin,
    vision,
)

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("api.start")
    ts = TimescaleStore.from_env()
    kg = KnowledgeGraph.from_env()
    bus = EventBus.from_env()
    await ts.connect()
    await kg.connect()
    app.state.ts = ts
    app.state.kg = kg
    app.state.bus = bus
    log.info("api.ready", ts_enabled=ts.enabled, kg_enabled=kg.enabled)
    try:
        yield
    finally:
        await ts.close()
        await kg.close()
        await bus.close()
        log.info("api.stop")


def create_app() -> FastAPI:
    app = FastAPI(
        title="DCOps Copilot API",
        version="0.3.0",
        description="Autonomous Multi-Site Data Center Operations Platform",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in os.getenv("API_CORS_ORIGINS", "http://localhost:3000").split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(telemetry.router,        prefix="/telemetry",        tags=["telemetry"])
    app.include_router(incidents.router,        prefix="/incidents",        tags=["incidents"])
    app.include_router(agents.router,           prefix="/agents",           tags=["agents"])
    app.include_router(twin.router,             prefix="/twin",             tags=["twin"])
    app.include_router(query.router,            prefix="/query",            tags=["query"])
    app.include_router(recommendations.router,  prefix="/recommendations",  tags=["recommendations"])
    app.include_router(forecasts.router,        prefix="/forecasts",        tags=["forecasts"])
    app.include_router(vision.router,           prefix="/vision",           tags=["vision"])
    app.include_router(fleet.router,            prefix="/fleet",            tags=["fleet"])
    app.include_router(federation.router,       prefix="/federation",       tags=["federation"])
    return app


app = create_app()
