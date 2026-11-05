from concurrent.futures import ThreadPoolExecutor

from task_api.tasks.store import TaskStore


def test_new_store_is_empty() -> None:
    assert TaskStore().list() == []


def test_ids_differ_for_equal_titles() -> None:
    store = TaskStore()
    a = store.add("same", None)
    b = store.add("same", None)
    assert a.id != b.id


def test_order_is_preserved() -> None:
    store = TaskStore()
    added = [store.add(t, "2030-01-01") for t in ("A", "B", "C")]
    assert store.list() == added


def test_list_returns_copy() -> None:
    store = TaskStore()
    store.add("A", None)
    store.list().clear()
    assert len(store.list()) == 1


def test_concurrent_add_loses_nothing() -> None:
    store = TaskStore()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: store.add(f"t{i}", None), range(400)))
    tasks = store.list()
    assert len(tasks) == 400
    assert len({t.id for t in tasks}) == 400
