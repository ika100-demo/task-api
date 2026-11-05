"""Prometheus metrics for task-api, recorded for every request by one middleware."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

ERROR_COUNT = Counter(
    "application_errors_total",
    "Total application errors",
    ["error_type"],
)

UNMATCHED = "unmatched"


def _route(request: Request) -> str:
    """Path template of the matched route, so /items/1 and /items/2 share one label."""
    route = request.scope.get("route")
    return str(getattr(route, "path", UNMATCHED)) if route is not None else UNMATCHED


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record count and duration of every request except scrapes of /metrics."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as exc:
            ERROR_COUNT.labels(error_type=type(exc).__name__).inc()
            raise
        finally:
            route = _route(request)
            REQUEST_COUNT.labels(request.method, route, str(status)).inc()
            REQUEST_LATENCY.labels(request.method, route).observe(time.perf_counter() - start)
