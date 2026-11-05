# Design — 002 Store tasks in Postgres instead of memory

## Decisions

- **Postgres through psycopg 3 and one `psycopg_pool.ConnectionPool` per process**, opened without waiting
  (`open(wait=False)`) when the store is constructed. The process therefore starts and `/health` answers while the
  database is down; the pool's background workers keep connecting (AC-002.10, AC-002.12). Sync driver and sync route
  handlers, the same model as spec 001 (FastAPI runs them in its threadpool). ADR:
  [docs/adr/001-postgres-task-storage.md](../../adr/001-postgres-task-storage.md).
- **Same store interface, new implementation.** `TaskStore` in `tasks/store.py` keeps its name, `TaskRecord` and
  `add()` / `list()`; its constructor now takes the connection string. `router.py` and `models.py` keep their logic;
  the router only gains the `503` in its OpenAPI declarations.
- **One domain exception, one handler.** The store translates every "the database cannot serve this" failure into
  `TaskStoreUnavailable`; an app-level exception handler turns it into `503 {"detail": "The task store is
  unavailable."}`. The router never sees psycopg types. Mapped: `psycopg.OperationalError` (connection refused/lost,
  `QueryCanceled` from `statement_timeout` is a subclass), `psycopg.InterfaceError` (connection closed under us),
  `psycopg_pool.PoolTimeout`, `psycopg_pool.PoolClosed`, and "no `DATABASE_URL` configured". Anything else
  propagates and is a `500` (contract: "`500` only for an unexpected fault unrelated to the database").
- **Validation before the database** is already guaranteed: FastAPI validates `TaskCreate` before the handler runs,
  so an invalid body is `422` even while the database is down (AC-002.7). Nothing to add; do not move any store call
  into a dependency that resolves before body validation.
- **Schema created lazily by the store, on the first successful checkout**, not at import or startup: a flag
  `_schema_ready` (guarded by a `threading.Lock`) is checked at the start of every `add()` / `list()`; while it is
  false the store runs the idempotent DDL on the connection it just checked out, commits, and sets the flag. A pod
  started while the database is down thus creates the table on its first request after recovery (AC-002.12). The DDL
  runs under `pg_advisory_xact_lock(1952539499)` so two instances starting together never race on
  `CREATE TABLE IF NOT EXISTS` (which can fail with a unique violation on `pg_type` when concurrent) (AC-002.13).
  If the DDL itself fails with a mapped error, the request is `503` and the flag stays false.
- **Order by the identity column `seq`**, never a timestamp: `seq` is assigned by Postgres at insert, monotonic
  across instances, so creation order is exact regardless of clock resolution and identical on every instance
  (AC-002.2, AC-002.3, AC-002.13).
- **`id` is generated in Python** (`uuid.uuid4()`, as in spec 001) and stored in a `uuid` column with a `UNIQUE`
  constraint; returned as `str(uuid)`, which is the canonical lowercase 8-4-4-4-12 form spec 001 already returned.
- **`due_date` stored as `date`**, returned as `date.isoformat()`. The validator only admits `YYYY-MM-DD` real dates
  with a year of 1 to 9999, for which `isoformat()` returns exactly the string sent (4-digit zero-padded year), so the
  round trip is lossless (AC-002.1).
- **`title` stored as `text`**, bound as a parameter, never trimmed (AC-002.1).
- **Timeouts as the contract states**, set on every pooled connection:
  `connect_timeout=2`, `options="-c statement_timeout=2000"`, pool checkout `timeout=2.0`. Worst case for a task route
  is checkout (2 s) + one statement (2 s) < 5 s (AC-002.4, AC-002.5, AC-002.6). A locked table makes the statement
  wait for the lock; `statement_timeout` cancels it (`QueryCanceled`), the transaction rolls back, nothing is stored
  (AC-002.6).
- **`/ready` checks out with a 1 s timeout** and runs `SELECT 1` (bounded by the 2 s `statement_timeout`), so it
  answers within 3 s (AC-002.10). It reflects the database on every call; no cached state (AC-002.11).
- **Broken connections are discarded on checkout** with `check=ConnectionPool.check_connection`: after a database
  restart the pooled connections are dead; the check drops them and the pool reconnects instead of handing a dead
  connection to a request (AC-002.11).
- **`reconnect_timeout=10`** (pool default is 300 s). After it the pool calls `reconnect_failed` and starts a new
  attempt with its backoff reset, so the gap between two connection attempts never grows beyond roughly 10 s. With the
  kubelet probe period of 10 s, `/ready` returns to `200` well inside the 30 s of AC-002.11 / AC-002.12.
- **App factory.** `main.py` gets `create_app(store: TaskStore | None = None) -> FastAPI`; the module-level
  `app = create_app()` builds `TaskStore(os.environ.get("DATABASE_URL"))`. Tests create independent "instances"
  (separate apps with separate pools on the same database) without subprocesses (AC-002.1, AC-002.2, AC-002.13).
  A lifespan handler closes the store's pool on shutdown.
- **Missing `DATABASE_URL` does not crash the process**: the store is "unconfigured", logs `task_store_unconfigured`
  once at construction (level error), `/ready` is `503`, task routes are `503`. This keeps `import task_api.main`
  side-effect-free enough for tests and keeps the "process always starts" rule; the gitops entry always sets the
  variable, so not-ready is the visible signal of a misconfiguration.
- **Multi-instance is now supported** (spec 001 single-process constraint lifted). The Dockerfile `CMD` is not
  changed; replicas are the gitops repo's business.
- **Dependencies** (runtime): `psycopg[binary]`, `psycopg-pool`; (dev extra): `testcontainers[postgres]`. Added with
  uv through devbox (`devbox run -- uv add ...`), never pip. `psycopg[binary]` ships libpq in manylinux wheels for
  amd64 and arm64, so the `python:3.12-slim` image needs no system packages.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/task_api/tasks/store.py` | `TaskRecord`, `TaskStoreUnavailable`, `TaskStore` (pool, lazy schema, `add`, `list`, `ping`, `close`) | changed (rewritten) |
| `src/task_api/errors.py` | adds `ErrorMessage` model and `task_store_unavailable_handler` (→ 503) | changed |
| `src/task_api/tasks/router.py` | declares `503` (`ErrorMessage`) on both operations | changed (decorators only) |
| `src/task_api/main.py` | `create_app()`, lifespan closing the store, `/ready` via `store.ping()`, registers the 503 handler | changed |
| `src/task_api/tasks/models.py` | unchanged | — |
| `pyproject.toml`, `uv.lock` | new dependencies | changed |
| `docs/env-vars.md` | documents `DATABASE_URL` | changed |

### Interfaces

```python
# tasks/store.py
@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: str; title: str; due_date: str | None          # unchanged

class TaskStoreUnavailable(Exception):                  # the only error the store raises for DB trouble
    ...

class TaskStore:
    def __init__(self, conninfo: str | None) -> None    # None/"" -> unconfigured; else opens the pool (wait=False)
    def add(self, title: str, due_date: str | None) -> TaskRecord   # committed when it returns
    def list(self) -> list[TaskRecord]                  # ORDER BY seq
    def ping(self, timeout: float = 1.0) -> None        # checkout(timeout) + SELECT 1; raises TaskStoreUnavailable
    def close(self) -> None                             # closes the pool; idempotent

# pool construction (inside TaskStore.__init__)
ConnectionPool(
    conninfo, min_size=1, max_size=10, timeout=2.0, reconnect_timeout=10.0,
    check=ConnectionPool.check_connection, name="task-api", open=False,
    kwargs={"connect_timeout": 2, "options": "-c statement_timeout=2000", "application_name": "task-api"},
).open(wait=False)

# errors.py
class ErrorMessage(BaseModel):
    detail: str
async def task_store_unavailable_handler(request: Request, exc: TaskStoreUnavailable) -> Response
    # -> JSONResponse(503, {"detail": "The task store is unavailable."}); logs task_store_unavailable (error class only)

# main.py
def create_app(store: TaskStore | None = None) -> FastAPI   # None -> TaskStore(os.environ.get("DATABASE_URL"))
app = create_app()
```

SQL (static strings, parameters bound by psycopg):

```sql
-- schema (once per store, in one transaction)
SELECT pg_advisory_xact_lock(1952539499);
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       uuid   NOT NULL UNIQUE,
    title    text   NOT NULL,
    due_date date   NULL
);
-- add
INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s);
-- list
SELECT id, title, due_date FROM tasks ORDER BY seq;
-- ping
SELECT 1;
```

Never log `DATABASE_URL`, connection strings or titles; log the exception class name only.

## Contract

Binding as written in the spec's "Contract" section; spec 001's contract (task object, validation, `422` body,
`405`, oldest-first bare array) is unchanged. Additions, as the testers' checklist:

- `POST /tasks`: `201` task object (committed before the response), `422` as spec 001 (checked before the
  database, also while it is down), **`503` `{"detail": "The task store is unavailable."}`** (exactly this body,
  `Content-Type: application/json`, no other fields, no `Retry-After`) when the store is unavailable; nothing is
  stored on `503`.
- `GET /tasks`: `200` bare array ordered by creation (`seq`), `[]` only when the table holds no row; **`503`** with the
  same body when the store is unavailable (never `200 []`).
- `GET /ready`: `200 {"status": "ready"}` when `SELECT 1` succeeds; `503 {"status": "not ready"}` otherwise, within
  3 s.
- `GET /health`: `200 {"status": "ok"}` always; never touches the database.
- `/openapi.json`: `paths["/tasks"]["post"]["responses"]` has `"201"`, `"422"`, `"503"`;
  `paths["/tasks"]["get"]["responses"]` has `"200"`, `"503"` (the `422` FastAPI adds is not required for GET). The 503
  response schema references `ErrorMessage` (`{"detail": string}`). `/ready` also declares `503`.
- `/ping`, `/metrics`, `/docs` unchanged.
- Timing: task routes answer within 5 s, `/ready` within 3 s, when the database is down, hanging on a lock, or slow.

### Test seam (for acceptance tests)

Tests run against a real Postgres (testcontainers-python, Docker). The testers own `tests/conftest.py`; coders do not
edit it. The seam the code provides:

```python
from task_api.main import app, create_app
from task_api.tasks.store import TaskStore

store = TaskStore(url)            # one "instance" = one store (own pool) ...
inst = create_app(store)          # ... wrapped in its own app; TestClient(inst)
store.close()                     # "stop the instance"
app.state.task_store = TaskStore(url)   # swapping the store of the module-level app still works
```

Recommended fixtures (tester's choice, listed so the code fits them):

- session-scoped `PostgresContainer("postgres:16-alpine", driver=None)` → `database_url`
  (`postgresql://...`, no `+psycopg2` suffix).
- autouse per test: `TRUNCATE tasks RESTART IDENTITY` when the table exists (spec 001 tests need an empty database
  per test; read AC-001.10 as "given the database holds no task").
- `client`: `TestClient(app)` with `app.state.task_store = TaskStore(database_url)`, so `tests/test_health.py`
  (`/ready` → `200`) passes unchanged.
- Outage and recovery (AC-002.4, .5, .10, .11, .12): a separate container bound to a fixed free host port
  (`with_bind_ports(5432, port)`), stopped and started with the Docker API; a random port would change on restart and
  the store's connection string would no longer reach it. "Unreachable from the start" can also be a store on a closed
  port (`postgresql://u:p@127.0.0.1:<closed>/db`).
- Hanging query (AC-002.6): a second psycopg session holding `BEGIN; LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE;`
  during the requests (the table must exist first: make one successful request before locking).
- Two instances (AC-002.13): two `create_app(TaskStore(database_url))` apps, requests from a thread pool.

Spec 001's `test_fresh_instance_is_empty` (AC-001.13) no longer applies; replace it with the AC-002.1 test.

## Data

Table `tasks` (`seq` bigint identity PK, `id` uuid unique not null, `title` text not null, `due_date` date null),
created by the store itself (no migration tool: non-goal). No index beyond PK and the unique `id`; the list reads
the whole table ordered by the PK (no paging: non-goal).

## Risks

- **Ambiguous commit**: if the connection drops after the server committed but before the client got the
  acknowledgement, `POST` answers `503` while the row exists. Inherent to any non-idempotent create; the contract
  already tells callers a failed `POST` "may or may not exist".
- **NUL characters**: a title containing `U+0000` passes spec 001's validation, but Postgres `text` cannot store it.
  psycopg raises a `DataError` (not mapped), so the request is `500`. Spec 001's tests do not send it; a later spec
  may reject it as `422`.
- **Recovery timing** depends on psycopg_pool's backoff; `reconnect_timeout=10` bounds the gap. AC-002.11 and
  AC-002.12 measure it; if they show more than ~20 s, lower `reconnect_timeout`, do not add a custom reconnect loop.
- **Tests need Docker** locally and in CI (`ubuntu-latest` has it). No SQLite fallback.
- A schema dropped by hand while the process runs is not recreated (`_schema_ready` stays true); out of scope.
