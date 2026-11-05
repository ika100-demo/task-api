"""FastAPI entry point for task-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from .errors import task_store_unavailable_handler, validation_exception_handler
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks.router import router
from .tasks.store import TaskStore, TaskStoreUnavailable
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    app.state.task_store.close()


def create_app(store: TaskStore | None = None) -> FastAPI:
    """Build the application, optionally with a given task store."""
    app = FastAPI(title="task-api", version="0.1.0", lifespan=_lifespan)
    app.state.task_store = store or TaskStore(os.environ.get("DATABASE_URL"))
    app.add_middleware(MetricsMiddleware)
    app.include_router(router)
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        TaskStoreUnavailable,
        task_store_unavailable_handler,  # type: ignore[arg-type]
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe — returns 200 as long as the process is responding."""
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
    def ready(request: Request) -> Response:
        """Readiness probe — 200 when the task store answers SELECT 1."""
        try:
            request.app.state.task_store.ping(timeout=1.0)
        except TaskStoreUnavailable:
            return JSONResponse(status_code=503, content={"status": "not ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "task-api"}

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
