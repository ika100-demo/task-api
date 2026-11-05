"""Acceptance tests for spec 002 (tasks in Postgres, 503 while the database is down)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

import pytest
from conftest import OutageDb, closed_port_url
from fastapi.testclient import TestClient

UNAVAILABLE = {"detail": "The task store is unavailable."}


@contextmanager
def instance(url: str) -> Iterator[TestClient]:
    """One task API instance: its own store (pool) in its own app."""
    from task_api.main import create_app
    from task_api.tasks.store import TaskStore

    store = TaskStore(url)
    try:
        yield TestClient(create_app(store))
    finally:
        store.close()


def poll(check: Callable[[], bool], timeout: float = 30.0, interval: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return True
        except Exception:  # noqa: BLE001 - the instance may still be reconnecting
            pass
        time.sleep(interval)
    return False


def create(client: TestClient, title: str, due_date: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"title": title}
    if due_date is not None:
        body["due_date"] = due_date
    resp = client.post("/tasks", json=body)
    assert resp.status_code == 201, resp.text
    result: dict[str, Any] = resp.json()
    return result


def assert_unavailable(resp: Any, started: float, limit: float = 5.0) -> None:
    elapsed = time.monotonic() - started
    assert resp.status_code == 503, resp.text
    assert resp.json() == UNAVAILABLE
    assert elapsed < limit, f"took {elapsed:.1f}s"


def test_restart_keeps_tasks(database_url: str) -> None:  # AC-002.1
    with instance(database_url) as first:
        a = create(first, "  Buy milk  ")
        b = create(first, "File taxes", "2026-12-31")
    with instance(database_url) as second:
        resp = second.get("/tasks")
    assert resp.status_code == 200
    assert resp.json() == [a, b]
    assert a["title"] == "  Buy milk  " and a["due_date"] is None
    assert b["due_date"] == "2026-12-31"


def test_redeploy_keeps_order_and_new_ids(database_url: str) -> None:  # AC-002.2
    with instance(database_url) as first:
        a = create(first, "A")
        b = create(first, "B")
    with instance(database_url) as second:
        c = create(second, "C")
        resp = second.get("/tasks")
    assert resp.status_code == 200
    assert resp.json() == [a, b, c]
    assert c["id"] not in (a["id"], b["id"])


def test_rapid_creates_keep_response_order(client: TestClient) -> None:  # AC-002.3
    created = [create(client, f"task {i}") for i in range(20)]
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert [t["id"] for t in resp.json()] == [t["id"] for t in created]


def test_post_while_db_down_is_503_and_stores_nothing(outage_db: OutageDb) -> None:  # AC-002.4
    with instance(outage_db.url) as inst:
        assert poll(lambda: inst.get("/ready").status_code == 200, 15)
        outage_db.stop()
        started = time.monotonic()
        resp = inst.post("/tasks", json={"title": "Lost task"})
        assert_unavailable(resp, started)
        outage_db.start()
        assert poll(lambda: inst.get("/tasks").status_code == 200)
        assert "Lost task" not in [t["title"] for t in inst.get("/tasks").json()]


def test_post_unreachable_from_start_is_503() -> None:  # AC-002.4
    with instance(closed_port_url()) as inst:
        started = time.monotonic()
        assert_unavailable(inst.post("/tasks", json={"title": "Lost task"}), started)


def test_get_while_db_down_is_503(outage_db: OutageDb) -> None:  # AC-002.5
    with instance(outage_db.url) as inst:
        create(inst, "Existing")
        assert inst.get("/tasks").status_code == 200
        outage_db.stop()
        started = time.monotonic()
        assert_unavailable(inst.get("/tasks"), started)


@pytest.mark.parametrize("method", ["get", "post"])
def test_locked_table_is_503(  # AC-002.6
    database_url: str, client: TestClient, method: str
) -> None:
    import psycopg

    create(client, "before lock")
    locker = psycopg.connect(database_url)
    try:
        locker.execute("LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        if method == "get":
            resp = client.get("/tasks")
        else:
            resp = client.post("/tasks", json={"title": "during lock"})
        assert_unavailable(resp, started)
    finally:
        locker.rollback()
        locker.close()
    titles = [t["title"] for t in client.get("/tasks").json()]
    assert "during lock" not in titles
    assert "before lock" in titles


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "x", "due_date": "tomorrow"}, "due_date"),
    ],
)
def test_invalid_body_is_422_while_db_down(payload: dict[str, Any], field: str) -> None:  # AC-002.7
    with instance(closed_port_url()) as inst:
        resp = inst.post("/tasks", json=payload)
        assert resp.status_code == 422
        assert any(e["loc"][-1] == field for e in resp.json()["detail"])


def test_openapi_lists_503(client: TestClient) -> None:  # AC-002.8
    paths = client.get("/openapi.json").json()["paths"]
    assert {"201", "422", "503"} <= set(paths["/tasks"]["post"]["responses"])
    assert {"200", "503"} <= set(paths["/tasks"]["get"]["responses"])


def test_ready_and_health_ok(client: TestClient) -> None:  # AC-002.9
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    assert client.get("/health").status_code == 200


def test_ready_503_when_db_goes_down(outage_db: OutageDb) -> None:  # AC-002.10
    with instance(outage_db.url) as inst:
        assert poll(lambda: inst.get("/ready").status_code == 200, 15)
        outage_db.stop()
        started = time.monotonic()
        resp = inst.get("/ready")
        elapsed = time.monotonic() - started
        assert resp.status_code == 503
        assert resp.json() == {"status": "not ready"}
        assert elapsed < 3, f"took {elapsed:.1f}s"
        assert inst.get("/health").status_code == 200


def test_recovers_without_restart(outage_db: OutageDb) -> None:  # AC-002.11
    with instance(outage_db.url) as inst:
        before = create(inst, "before outage")
        outage_db.stop()
        assert inst.get("/ready").status_code == 503
        outage_db.start()
        assert poll(lambda: inst.get("/ready").status_code == 200, 30)
        resp = inst.get("/tasks")
        assert resp.status_code == 200 and before in resp.json()
        assert inst.post("/tasks", json={"title": "after outage"}).status_code == 201


def test_starts_without_db_and_recovers(outage_db: OutageDb) -> None:  # AC-002.12
    outage_db.stop()
    with instance(outage_db.url) as inst:
        assert inst.get("/health").status_code == 200
        assert inst.get("/ready").status_code == 503
        outage_db.start()
        assert poll(lambda: inst.get("/ready").status_code == 200, 30)
        resp = inst.get("/tasks")
        assert resp.status_code == 200 and resp.json() == []
        assert inst.post("/tasks", json={"title": "first"}).status_code == 201


def test_two_instances_share_one_list(database_url: str) -> None:  # AC-002.13
    with instance(database_url) as one, instance(database_url) as two:

        def make(args: tuple[TestClient, int]) -> int:
            client, i = args
            return client.post("/tasks", json={"title": f"t{i}"}).status_code

        jobs = [(c, i) for i in range(10) for c in (one, two)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert set(pool.map(make, jobs)) == {201}
        lists = []
        for i in range(10):
            resp = (one, two)[i % 2].get("/tasks")
            assert resp.status_code == 200
            lists.append(resp.json())
        ids = [[t["id"] for t in tasks] for tasks in lists]
        assert all(len(x) == 20 and len(set(x)) == 20 for x in ids)
        assert all(x == ids[0] for x in ids)


def test_spec_001_runs_on_the_database(database_url: str, client: TestClient) -> None:  # AC-002.14
    import psycopg

    created = create(client, "in the database")
    with psycopg.connect(database_url) as conn:
        rows = conn.execute("SELECT id::text, title FROM tasks").fetchall()
    assert rows == [(created["id"], "in the database")]


def test_store_raises_unavailable_on_closed_port() -> None:  # AC-002.5
    from task_api.tasks.store import TaskStore, TaskStoreUnavailable

    store = TaskStore(closed_port_url())
    try:
        with pytest.raises(TaskStoreUnavailable):
            store.list()
    finally:
        store.close()
