"""Every request is recorded by the metrics middleware (spec 104)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from task_api.main import app


def _value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _boom() -> None:
    raise ValueError("boom")


def _item(id: str) -> dict[str, str]:
    return {"id": id}


def _extra(app: FastAPI) -> None:
    if not any(getattr(r, "path", "") == "/items/{id}" for r in app.routes):
        app.add_api_route("/items/{id}", _item, methods=["GET"])
        app.add_api_route("/boom", _boom, methods=["GET"])
        app.add_api_route("/added", lambda: {"ok": True}, methods=["GET"])


@pytest.fixture()
def metrics_client() -> Iterator[TestClient]:
    _extra(app)
    yield TestClient(app, raise_server_exceptions=False)


def test_added_endpoint_and_404_are_counted_with_duration(metrics_client: TestClient) -> None:
    """AC-104.4: an added endpoint and a 404 path show count and duration."""
    count = {"method": "GET", "route": "/added", "status_code": "200"}
    before = _value("http_requests_total", **count)
    before_404 = _value("http_requests_total", method="GET", route="unmatched", status_code="404")
    assert metrics_client.get("/added").status_code == 200
    assert metrics_client.get("/nowhere").status_code == 404
    assert _value("http_requests_total", **count) == before + 1
    assert _value("http_request_duration_seconds_count", method="GET", route="/added") >= 1
    assert (
        _value("http_requests_total", method="GET", route="unmatched", status_code="404")
        == before_404 + 1
    )
    assert _value("http_request_duration_seconds_count", method="GET", route="unmatched") >= 1


def test_variable_paths_count_under_one_route(metrics_client: TestClient) -> None:
    """AC-104.5: /items/123 and /items/456 share /items/{id}; unknown paths share one label."""
    labels = {"method": "GET", "route": "/items/{id}", "status_code": "200"}
    before = _value("http_requests_total", **labels)
    metrics_client.get("/items/123")
    metrics_client.get("/items/456")
    assert _value("http_requests_total", **labels) == before + 2
    metrics_client.get("/unknown-a")
    metrics_client.get("/unknown-b")
    assert _value("http_requests_total", method="GET", route="/items/123", status_code="200") == 0
    assert _value("http_requests_total", method="GET", route="/unknown-a", status_code="404") == 0
    routes = {
        s.labels["route"]
        for m in REGISTRY.collect()
        if m.name == "http_requests"
        for s in m.samples
    }
    assert "/unknown-a" not in routes and "/unknown-b" not in routes and "unmatched" in routes


def test_unhandled_error_is_500_and_counted(metrics_client: TestClient) -> None:
    """AC-104.6: a raising handler gives 500, counted, plus one application error."""
    labels = {"method": "GET", "route": "/boom", "status_code": "500"}
    before = _value("http_requests_total", **labels)
    errors = _value("application_errors_total", error_type="ValueError")
    assert metrics_client.get("/boom").status_code == 500
    assert _value("http_requests_total", **labels) == before + 1
    assert _value("application_errors_total", error_type="ValueError") == errors + 1


def test_scraping_metrics_adds_nothing(metrics_client: TestClient) -> None:
    """AC-104.7: a /metrics scrape is not recorded in the request metrics."""
    health = {"method": "GET", "route": "/health", "status_code": "200"}
    health_before = _value("http_requests_total", **health)
    metrics_client.get("/health")
    assert (
        _value("http_requests_total", **health) == health_before + 1
    )  # the middleware is recording at all
    before = metrics_client.get("/metrics").text
    metrics_client.get("/metrics")
    after = metrics_client.get("/metrics").text
    assert 'route="/metrics"' not in after
    assert [ln for ln in before.splitlines() if ln.startswith("http_request")] == [
        ln for ln in after.splitlines() if ln.startswith("http_request")
    ]
