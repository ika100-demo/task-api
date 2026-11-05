"""Postgres-backed task storage (psycopg pool, lazily created schema)."""

import datetime
import threading
import uuid
from dataclasses import dataclass

import psycopg
import structlog
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

logger = structlog.get_logger(__name__)

_SCHEMA_LOCK_KEY = 1952539499
_UNAVAILABLE_ERRORS = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    PoolTimeout,
    PoolClosed,
)


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: str
    title: str
    due_date: str | None


class TaskStoreUnavailable(Exception):  # noqa: N818
    """The database cannot serve the call."""


class TaskStore:
    def __init__(self, conninfo: str | None = None) -> None:
        self._pool: ConnectionPool | None = None
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        if not conninfo:
            logger.error("task_store_unconfigured")
            return
        pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=10,
            timeout=2.0,
            reconnect_timeout=10.0,
            check=ConnectionPool.check_connection,
            name="task-api",
            open=False,
            kwargs={
                "connect_timeout": 2,
                "options": "-c statement_timeout=2000",
                "application_name": "task-api",
            },
        )
        pool.open(wait=False)
        self._pool = pool

    def _require_pool(self) -> ConnectionPool:
        if self._pool is None:
            raise TaskStoreUnavailable("task store is not configured")
        return self._pool

    def _ensure_schema(self, conn: psycopg.Connection) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS tasks ("
                    "seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                    "id uuid NOT NULL UNIQUE, "
                    "title text NOT NULL, "
                    "due_date date NULL)"
                )
            self._schema_ready = True

    def add(self, title: str, due_date: str | None) -> TaskRecord:
        pool = self._require_pool()
        task_id = uuid.uuid4()
        due = datetime.date.fromisoformat(due_date) if due_date else None
        try:
            with pool.connection() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)",
                    (task_id, title, due),
                )
        except _UNAVAILABLE_ERRORS as exc:
            raise TaskStoreUnavailable(type(exc).__name__) from exc
        return TaskRecord(id=str(task_id), title=title, due_date=due_date)

    def list(self) -> list[TaskRecord]:
        pool = self._require_pool()
        try:
            with pool.connection() as conn:
                self._ensure_schema(conn)
                rows = conn.execute("SELECT id, title, due_date FROM tasks ORDER BY seq").fetchall()
        except _UNAVAILABLE_ERRORS as exc:
            raise TaskStoreUnavailable(type(exc).__name__) from exc
        return [
            TaskRecord(str(row[0]), row[1], row[2].isoformat() if row[2] else None) for row in rows
        ]

    def ping(self, timeout: float = 1.0) -> None:
        pool = self._require_pool()
        try:
            with pool.connection(timeout=timeout) as conn:
                conn.execute("SELECT 1")
        except _UNAVAILABLE_ERRORS as exc:
            raise TaskStoreUnavailable(type(exc).__name__) from exc

    def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.close()
