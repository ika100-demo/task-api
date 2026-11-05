import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from task_api.tasks.store import TaskStore, TaskStoreUnavailable
from tests.conftest import closed_port_url


@pytest.fixture()
def store(database_url: str):  # type: ignore[no-untyped-def]
    s = TaskStore(database_url)
    yield s
    s.close()


def test_new_store_is_empty(store: TaskStore) -> None:
    assert store.list() == []


def test_ids_differ_for_equal_titles(store: TaskStore) -> None:
    a = store.add("same", None)
    b = store.add("same", None)
    assert a.id != b.id


def test_order_is_preserved(store: TaskStore) -> None:
    added = [store.add(t, "2030-01-01") for t in ("A", "B", "C")]
    assert store.list() == added


def test_untrimmed_title_and_due_date_round_trip(store: TaskStore) -> None:
    a = store.add("  Buy milk  ", None)
    b = store.add("File taxes", "2026-12-31")
    assert store.list() == [a, b]
    assert a.title == "  Buy milk  "
    assert b.due_date == "2026-12-31"


def test_concurrent_add_loses_nothing(store: TaskStore) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: store.add(f"t{i}", None), range(80)))
    tasks = store.list()
    assert len(tasks) == 80
    assert len({t.id for t in tasks}) == 80


def test_schema_creation_idempotent_across_stores(database_url: str) -> None:
    first, second = TaskStore(database_url), TaskStore(database_url)
    try:
        a = first.add("A", None)
        b = second.add("B", None)
        assert first.list() == [a, b] == second.list()
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("conninfo", [None, "", "closed"])
def test_unavailable_store_raises(conninfo: str | None) -> None:
    s = TaskStore(closed_port_url() if conninfo == "closed" else conninfo)
    try:
        for call in (lambda: s.add("x", None), s.list, s.ping):
            start = time.monotonic()
            with pytest.raises(TaskStoreUnavailable):
                call()
            assert time.monotonic() - start < 3
    finally:
        s.close()


def test_close_twice_is_fine(database_url: str) -> None:
    s = TaskStore(database_url)
    s.close()
    s.close()
    TaskStore(None).close()
