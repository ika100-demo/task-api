"""Smoke tests for spec 002: reach the service only through SMOKE_BASE_URL."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.smoke
def test_smoke_ac_002_8_openapi_lists_503(smoke_base_url: str) -> None:  # AC-002.8
    paths = httpx.get(smoke_base_url + "/openapi.json", timeout=10).json()["paths"]
    assert "503" in paths["/tasks"]["post"]["responses"]
    assert "503" in paths["/tasks"]["get"]["responses"]


@pytest.mark.smoke
def test_smoke_ac_002_9_ready_and_health_ok(smoke_base_url: str) -> None:  # AC-002.9
    ready = httpx.get(smoke_base_url + "/ready", timeout=10)
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert httpx.get(smoke_base_url + "/health", timeout=10).status_code == 200
