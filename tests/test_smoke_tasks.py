"""Smoke tests for spec 001: reach the service only through SMOKE_BASE_URL.

They create their own uniquely named data and never assume an empty list.
"""

from __future__ import annotations

import uuid

import httpx
import pytest


def _create(base: str, **body: object) -> httpx.Response:
    return httpx.post(base + "/tasks", json=body, timeout=10)


@pytest.mark.smoke
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    resp = _create(smoke_base_url, title=title)
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"id", "title", "due_date"}
    assert body["id"] and body["title"] == title and body["due_date"] is None


@pytest.mark.smoke
def test_smoke_ac_001_3_create_task_with_due_date(smoke_base_url: str) -> None:  # AC-001.3
    resp = _create(smoke_base_url, title=f"smoke-{uuid.uuid4()}", due_date="2026-12-31")
    assert resp.status_code == 201
    assert resp.json()["due_date"] == "2026-12-31"


@pytest.mark.smoke
def test_smoke_ac_001_4_ids_differ(smoke_base_url: str) -> None:  # AC-001.4
    title = f"smoke-{uuid.uuid4()}"
    a = _create(smoke_base_url, title=title)
    b = _create(smoke_base_url, title=title)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.smoke
def test_smoke_ac_001_5_blank_title_rejected(smoke_base_url: str) -> None:  # AC-001.5
    resp = _create(smoke_base_url, title="   ")
    assert resp.status_code == 422
    assert any(e["loc"][-1] == "title" for e in resp.json()["detail"])


@pytest.mark.smoke
def test_smoke_ac_001_7_bad_due_date_rejected(smoke_base_url: str) -> None:  # AC-001.7
    resp = _create(smoke_base_url, title=f"smoke-{uuid.uuid4()}", due_date="tomorrow")
    assert resp.status_code == 422
    assert any(e["loc"][-1] == "due_date" for e in resp.json()["detail"])


@pytest.mark.smoke
def test_smoke_ac_001_16_repeated_list_includes_task(smoke_base_url: str) -> None:  # AC-001.16
    task = _create(smoke_base_url, title=f"smoke-{uuid.uuid4()}").json()
    for _ in range(10):
        resp = httpx.get(smoke_base_url + "/tasks", timeout=10)
        assert resp.status_code == 200
        assert task in resp.json()


@pytest.mark.smoke
def test_smoke_ac_001_17_openapi_describes_tasks(smoke_base_url: str) -> None:  # AC-001.17
    spec = httpx.get(smoke_base_url + "/openapi.json", timeout=10).json()
    assert {"post", "get"} <= set(spec["paths"]["/tasks"])
    assert {"id", "title", "due_date"} <= set(spec["components"]["schemas"]["Task"]["properties"])
    assert httpx.get(smoke_base_url + "/health", timeout=10).status_code == 200
