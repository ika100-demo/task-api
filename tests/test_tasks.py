"""Acceptance tests for spec 001 (create and list tasks in memory)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from task_api.main import app


@pytest.fixture(autouse=True)
def _fresh_store() -> Iterator[None]:
    from task_api.tasks.store import TaskStore

    app.state.task_store = TaskStore()
    yield


def _ids(resp_json: Any) -> list[str]:
    return [t["id"] for t in resp_json]


def _assert_names(resp: Any, field: str) -> None:
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(e["loc"][-1] == field for e in detail), detail


def test_create_task_minimal(client: TestClient) -> None:  # AC-001.1
    resp = client.post("/tasks", json={"title": "Buy milk"})
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"id", "title", "due_date"}
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Buy milk", "due_date": None},
        {"title": "Buy milk", "colour": "red"},
    ],
)
def test_null_due_date_extra_field(client: TestClient, payload: dict[str, Any]) -> None:  # AC-001.2
    resp = client.post("/tasks", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["due_date"] is None
    assert "colour" not in body


def test_create_task_with_due_date(client: TestClient) -> None:  # AC-001.3
    resp = client.post("/tasks", json={"title": "File taxes", "due_date": "2026-12-31"})
    assert resp.status_code == 201
    assert resp.json()["due_date"] == "2026-12-31"


def test_ids_are_unique(client: TestClient) -> None:  # AC-001.4
    a = client.post("/tasks", json={"title": "same"})
    b = client.post("/tasks", json={"title": "same"})
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "\t\n"},
        {"title": " 　"},
        {"title": 42},
        {"title": None},
        {"title": ["x"]},
    ],
)
def test_invalid_title_rejected(client: TestClient, payload: dict[str, Any]) -> None:  # AC-001.5
    before = client.get("/tasks").json()
    resp = client.post("/tasks", json=payload)
    _assert_names(resp, "title")
    assert client.get("/tasks").json() == before


@pytest.mark.parametrize("raw", ["[]", '"text"', "not json{"])
def test_non_object_body_rejected(client: TestClient, raw: str) -> None:  # AC-001.6
    before = client.get("/tasks").json()
    resp = client.post("/tasks", content=raw, headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert any(e["loc"] == ["body"] for e in resp.json()["detail"])
    assert client.get("/tasks").json() == before


@pytest.mark.parametrize(
    "due",
    ["31.12.2026", "2026-02-30", "tomorrow", "2026-1-5", "2026-12-31T10:00:00", "", 42],
)
def test_invalid_due_date_rejected(client: TestClient, due: Any) -> None:  # AC-001.7
    before = client.get("/tasks").json()
    resp = client.post("/tasks", json={"title": "ok", "due_date": due})
    _assert_names(resp, "due_date")
    assert client.get("/tasks").json() == before


def test_both_fields_invalid(client: TestClient) -> None:  # AC-001.8
    resp = client.post("/tasks", json={"title": "", "due_date": "tomorrow"})
    assert resp.status_code == 422
    last = [e["loc"][-1] for e in resp.json()["detail"]]
    assert "title" in last and "due_date" in last


def test_title_length_limit(client: TestClient) -> None:  # AC-001.9
    for title in ("a" * 201, "ä" * 201, "\U0001f600" * 201, " " * 201):
        before = client.get("/tasks").json()
        _assert_names(client.post("/tasks", json={"title": title}), "title")
        assert client.get("/tasks").json() == before
    for title in ("a" * 200, "ä" * 200, "\U0001f600" * 200):
        resp = client.post("/tasks", json={"title": title})
        assert resp.status_code == 201
        assert resp.json()["title"] == title


def test_list_empty(client: TestClient) -> None:  # AC-001.10
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_in_creation_order(client: TestClient) -> None:  # AC-001.11
    created = [
        client.post("/tasks", json={"title": t, "due_date": d}).json()
        for t, d in (("A", None), ("B", "2026-01-01"), ("C", None))
    ]
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert resp.json() == created
    assert [t["title"] for t in resp.json()] == ["A", "B", "C"]
    assert all(set(t) == {"id", "title", "due_date"} for t in resp.json())


def test_list_ignores_query_params(client: TestClient) -> None:  # AC-001.12
    client.post("/tasks", json={"title": "A"})
    client.post("/tasks", json={"title": "B"})
    plain = client.get("/tasks")
    assert plain.status_code == 200 and len(plain.json()) == 2
    assert client.get("/tasks?limit=1&foo=bar").json() == plain.json()


def test_fresh_instance_is_empty(client: TestClient) -> None:  # AC-001.13
    from task_api.tasks.store import TaskStore

    assert client.post("/tasks", json={"title": "A"}).status_code == 201
    assert len(client.get("/tasks").json()) == 1
    app.state.task_store = TaskStore()
    assert client.get("/tasks").json() == []


def test_past_and_today_due_dates(client: TestClient) -> None:  # AC-001.14
    import datetime

    resp = client.post("/tasks", json={"title": "Old errand", "due_date": "2020-01-15"})
    assert resp.status_code == 201
    assert resp.json()["due_date"] == "2020-01-15"
    today = datetime.date.today().isoformat()
    resp = client.post("/tasks", json={"title": "Today", "due_date": today})
    assert resp.status_code == 201
    assert resp.json()["due_date"] == today


def test_title_not_trimmed(client: TestClient) -> None:  # AC-001.15
    resp = client.post("/tasks", json={"title": "  Buy milk  "})
    assert resp.status_code == 201
    assert resp.json()["title"] == "  Buy milk  "
    assert client.get("/tasks").json()[0]["title"] == "  Buy milk  "


def test_repeated_gets_include_task(client: TestClient) -> None:  # AC-001.16
    task = client.post("/tasks", json={"title": "A"}).json()
    for _ in range(10):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert task in resp.json()


def test_openapi_and_existing_endpoints(client: TestClient) -> None:  # AC-001.17
    spec = client.get("/openapi.json").json()
    assert {"post", "get"} <= set(spec["paths"]["/tasks"])
    assert set(spec["components"]["schemas"]["Task"]["properties"]) == {
        "id",
        "title",
        "due_date",
    }
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    assert client.get("/ping").json() == {"pong": "task-api"}
    assert client.get("/metrics").status_code == 200


@pytest.mark.parametrize("method", ["delete", "put"])
def test_other_methods_not_allowed(client: TestClient, method: str) -> None:  # AC-001.18
    client.post("/tasks", json={"title": "A"})
    before = client.get("/tasks").json()
    assert len(before) == 1
    assert client.request(method.upper(), "/tasks").status_code == 405
    assert client.get("/tasks").json() == before
