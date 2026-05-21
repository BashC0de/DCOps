"""FastAPI application entry point.

Purpose:
    HTTP + WebSocket API for the Next.js dashboard. Endpoint groups:
      /telemetry  — recent telemetry by site / device / metric
      /incidents  — incident timeline + per-incident detail + audit lineage
      /agents     — agent health + recent decisions
      /twin       — current physical/thermal state for the digital twin
      /query      — proxy to Operator agent
      /ws         — WebSocket for live incident push

Ships: Week 1 (skeleton); routes implemented across Weeks 2-10.

Run locally: `uvicorn apps.api.main:app --reload --port 8080`
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.agents.shared.logging import configure_logging, get_logger
from apps.api.routes import agents, incidents, query, telemetry, twin

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("api.start")
    # TODO(week-2): open shared DB pools (Timescale, Neo4j, Chroma) on _app.state.
    yield
    log.info("api.stop")


def create_app() -> FastAPI:
    app = FastAPI(
        title="DCOps Copilot API",
        version="0.1.0",
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

    app.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
    app.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
    app.include_router(agents.router,    prefix="/agents",    tags=["agents"])
    app.include_router(twin.router,      prefix="/twin",      tags=["twin"])
    app.include_router(query.router,     prefix="/query",     tags=["query"])
    return app


app = create_app()
