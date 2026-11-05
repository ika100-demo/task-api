---
spec_id: 002-store-tasks-in-postgres-instead-of
shape: service-python
spec_hash: d195d4899ce8
summary: Postgres-backed TaskStore (psycopg 3 pool, self-created schema, seq order), 503 on store failure, /ready via SELECT 1
tasks:
  - id: t1
    title: Replace the in-memory TaskStore with a Postgres store (psycopg pool, lazy schema)
    files: [pyproject.toml, uv.lock, src/task_api/tasks/store.py, tests/test_unit_task_store.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.11, AC-002.12, AC-002.13, AC-002.14]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Map store failures to 503, readiness via SELECT 1, app factory and env docs
    files: [src/task_api/errors.py, src/task_api/tasks/router.py, src/task_api/main.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.8, AC-002.9, AC-002.10, AC-002.11, AC-002.12, AC-002.13, AC-002.14]
    parallel_safe: false
    depends_on: [t1]
---

# Plan — 002 Store tasks in Postgres instead of memory

Design: [design.md](design.md). ADR: [001-postgres-task-storage](../../adr/001-postgres-task-storage.md).
Levels: t1 → t2.

The acceptance tests and the test fixtures (`tests/conftest.py` with the Postgres testcontainer, the adapted store
fixture in `tests/test_tasks.py`, the removal of the AC-001.13 test) are written by the testers before coding and are
not edited by the coders. No gitops task: the `postgres` resource and `DATABASE_URL` / `PG*` env are already wired in
the gitops-app. No Dockerfile change.

## t1 — Replace the in-memory TaskStore with a Postgres store (psycopg pool, lazy schema)

**Files:** pyproject.toml, uv.lock, src/task_api/tasks/store.py, tests/test_unit_task_store.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.11, AC-002.12, AC-002.13, AC-002.14
**Goal:** a `TaskStore` with the same `add()` / `list()` interface that persists tasks in Postgres, survives
outages without crashing, and raises one domain exception whenever the database cannot serve a call.

**Implementation notes:**
- Dependencies through devbox and uv, never pip: `devbox run -- uv add "psycopg[binary]" psycopg-pool` and
  `devbox run -- uv add --optional dev "testcontainers[postgres]"`. Commit `pyproject.toml` and `uv.lock`.
- Keep `TaskRecord` unchanged. Add `class TaskStoreUnavailable(Exception)`.
- `TaskStore.__init__(conninfo: str | None)`: empty/None → unconfigured (no pool; log `task_store_unconfigured`
  once at error level; every call raises `TaskStoreUnavailable`). Otherwise build the `ConnectionPool` exactly as in
  the design's Interfaces (min 1, max 10, `timeout=2.0`, `reconnect_timeout=10.0`,
  `check=ConnectionPool.check_connection`, kwargs `connect_timeout=2`, `options="-c statement_timeout=2000"`,
  `application_name="task-api"`, `open=False`) and call `open(wait=False)`. Never block or raise on an unreachable
  database here.
- Lazy schema: `_schema_ready` flag + `threading.Lock`; at the start of `add`/`list`, on the checked-out connection,
  if not ready run `SELECT pg_advisory_xact_lock(1952539499)` and the `CREATE TABLE IF NOT EXISTS tasks (...)` DDL
  from the design in one transaction, commit, set the flag. Not at import, not in `__init__`.
- `add`: `uuid.uuid4()`, `INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)` with `uuid.UUID`,
  untrimmed `title`, `datetime.date.fromisoformat(due_date)` or `None`; commit before returning the `TaskRecord`
  (id `str(uuid)`, title and due_date as passed in).
- `list`: `SELECT id, title, due_date FROM tasks ORDER BY seq` → `TaskRecord(str(id), title,
  due.isoformat() if due else None)`.
- `ping(timeout: float = 1.0)`: `pool.connection(timeout=timeout)` + `SELECT 1`.
- `close()`: close the pool if any; idempotent.
- Wrap every pool/connection use so `psycopg.OperationalError`, `psycopg.InterfaceError`, `psycopg_pool.PoolTimeout`
  and `psycopg_pool.PoolClosed` become `raise TaskStoreUnavailable(...) from exc`; any other exception propagates.
  Static SQL only (bandit), never log the conninfo or titles.
- Rewrite `tests/test_unit_task_store.py` against the Postgres fixture from `tests/conftest.py`: empty store lists
  `[]`; ids differ for equal titles; order preserved; untrimmed title and `due_date` round-trip; concurrent `add`
  from 8 threads loses nothing; schema creation is idempotent across two stores; an unconfigured store and a store on a
  closed port raise `TaskStoreUnavailable` from `add`, `list` and `ping` within 3 s; `close()` twice is fine.

**Done when:** the unit tests pass and `devbox run quality` is green. The HTTP acceptance tests need t2.

## t2 — Map store failures to 503, readiness via SELECT 1, app factory and env docs

**Files:** src/task_api/errors.py, src/task_api/tasks/router.py, src/task_api/main.py, docs/env-vars.md
**Covers:** AC-002.1 to AC-002.14
**Goal:** expose the Postgres store over the unchanged spec 001 contract plus the `503`, make `/ready` reflect the
database while `/health` never does, and give tests independent app instances.

**Implementation notes:**
- `errors.py`: `class ErrorMessage(BaseModel): detail: str`; `async def task_store_unavailable_handler(request,
  exc: TaskStoreUnavailable) -> Response` returning `JSONResponse(status_code=503, content={"detail": "The task store
  is unavailable."})` and logging `task_store_unavailable` via structlog with `error=type(exc.__cause__).__name__`
  (no message text, no URL). Keep `validation_exception_handler` unchanged.
- `router.py`: add `responses={503: {"model": ErrorMessage, "description": "The task store is unavailable"}}` to both
  decorators. Handler bodies, `get_task_store` and `_to_task` stay as they are; no store call before body validation.
- `main.py`: `def create_app(store: TaskStore | None = None) -> FastAPI` building everything the module does today
  (middleware, router, validation handler, `/health`, `/ready`, `/ping`, `/metrics`) on a new app;
  `store or TaskStore(os.environ.get("DATABASE_URL"))` on `app.state.task_store`; register
  `TaskStoreUnavailable → task_store_unavailable_handler`; a lifespan that calls `app.state.task_store.close()` on
  shutdown. Keep `configure_logging` / `configure_tracing` at module level (once per process). `app = create_app()`.
- `/ready` (sync): `request.app.state.task_store.ping(timeout=1.0)` → `{"status": "ready"}`; on
  `TaskStoreUnavailable` return `JSONResponse(503, {"status": "not ready"})`; declare `responses={503: {"model":
  HealthResponse}}`. `/health` stays `{"status": "ok"}` and never touches the store.
- Keep FastAPI `title`/`version` and every existing path unchanged; do not touch the Dockerfile.
- `docs/env-vars.md`: a "Database" section with `DATABASE_URL` (no default; unset → not ready and task routes `503`;
  set by the gitops-app from the `postgres` resource) and a note that libpq also reads `PGHOST`, `PGPORT`,
  `PGDATABASE`, `PGUSER`, `PGPASSWORD` for parts missing from the URL; list the fixed timeouts (connect 2 s, checkout
  2 s, statement 2 s, `/ready` checkout 1 s).
- Check `/openapi.json` lists `"503"` under `post` and `get` of `/tasks`.

**Done when:** all acceptance tests for AC-002.1 to AC-002.14 pass (including spec 001's adapted tests and the
outage/recovery timing tests), `tests/test_health.py`, `tests/test_metrics.py` and `tests/test_tracing.py` still pass,
and `devbox run ci` is green.
