"""Shared pytest fixtures: a real Postgres (testcontainers) behind the task API."""

from __future__ import annotations

import socket
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from task_api.main import app

POSTGRES_IMAGE = "postgres:16-alpine"


def free_port() -> int:
    """A free TCP port on localhost (closed again when this returns)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def closed_port_url() -> str:
    """A connection string nobody listens on: 'unreachable from the start'."""
    return f"postgresql://u:p@127.0.0.1:{free_port()}/db"


def wait_for_postgres(url: str, timeout: float = 60.0) -> None:
    """Block until a plain psycopg connection to `url` works."""
    import psycopg

    deadline = time.monotonic() + timeout
    while True:
        try:
            with psycopg.connect(url, connect_timeout=2):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.3)


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    """`postgresql://...` URL of the session-wide Postgres."""
    return postgres_container.get_connection_url()


@pytest.fixture(autouse=True)
def _empty_database(request: pytest.FixtureRequest) -> None:
    """Every test that uses the shared database starts with no task in it."""
    if "database_url" not in request.fixturenames:
        return
    url: str = request.getfixturevalue("database_url")
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('public.tasks')").fetchone()
        if exists and exists[0] is not None:
            conn.execute("TRUNCATE tasks RESTART IDENTITY")


@pytest.fixture()
def client(database_url: str) -> Iterator[TestClient]:
    """A TestClient for the module-level app, backed by the shared Postgres."""
    from task_api.tasks.store import TaskStore

    store = TaskStore(database_url)
    app.state.task_store = store
    try:
        yield TestClient(app)
    finally:
        store.close()


class OutageDb:
    """A Postgres on a fixed host port that tests can stop and start."""

    def __init__(self) -> None:
        self.port = free_port()
        self.container = PostgresContainer(POSTGRES_IMAGE, driver=None)
        self.container.with_bind_ports(5432, self.port)
        self.container.start()
        self.url = (
            f"postgresql://{self.container.username}:{self.container.password}"
            f"@127.0.0.1:{self.port}/{self.container.dbname}"
        )
        self.wait_ready()

    @property
    def _docker(self) -> Any:
        return self.container.get_wrapped_container()

    def stop(self) -> None:
        self._docker.stop(timeout=2)

    def start(self) -> None:
        self._docker.reload()
        if self._docker.status != "running":
            self._docker.start()
        self.wait_ready()

    def wait_ready(self) -> None:
        wait_for_postgres(self.url)

    def drop_tasks(self) -> None:
        import psycopg

        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS tasks")


@pytest.fixture(scope="session")
def _outage_db_session() -> Iterator[OutageDb]:
    db = OutageDb()
    try:
        yield db
    finally:
        db.container.stop()


@pytest.fixture()
def outage_db(_outage_db_session: OutageDb) -> Iterator[OutageDb]:
    """The stoppable Postgres, running and without a tasks table; running again afterwards."""
    db = _outage_db_session
    db.start()
    db.drop_tasks()
    try:
        yield db
    finally:
        db.start()
