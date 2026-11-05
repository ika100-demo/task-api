---
spec_id: 001-create-and-list-tasks-in-memory-post
shape: service-python
spec_hash: ce169315232a
summary: In-memory task store with POST /tasks (validated create) and GET /tasks (list in creation order)
tasks:
  - id: t1
    title: Add TaskCreate and Task models with strict validation
    files: [src/task_api/tasks/__init__.py, src/task_api/tasks/models.py, tests/test_unit_task_models.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.5, AC-001.7, AC-001.8, AC-001.9, AC-001.14, AC-001.15, AC-001.17]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add thread-safe in-memory TaskStore
    files: [src/task_api/tasks/store.py, tests/test_unit_task_store.py]
    covers: [AC-001.4, AC-001.10, AC-001.11, AC-001.13, AC-001.16]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Wire POST/GET /tasks router, validation error handler and app store
    files: [src/task_api/tasks/router.py, src/task_api/errors.py, src/task_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11, AC-001.12, AC-001.13, AC-001.14, AC-001.15, AC-001.16, AC-001.17, AC-001.18]
    parallel_safe: false
    depends_on: [t1, t2]
---

# Plan — 001 Create and list tasks in memory

Design: [design.md](design.md). Levels: t1, t2 (parallel) → t3.

## t1 — Add TaskCreate and Task models with strict validation

**Files:** src/task_api/tasks/__init__.py, src/task_api/tasks/models.py, tests/test_unit_task_models.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.5, AC-001.7, AC-001.8, AC-001.9, AC-001.14, AC-001.15, AC-001.17
**Goal:** the request and response models that encode every input rule of the contract, so the router only has to
declare them.

**Implementation notes:**
- Create the package `task_api.tasks` (`__init__.py` with a docstring only).
- `TaskCreate`: `title: StrictStr` with `Field(max_length=200)`; a `field_validator("title")` rejecting
  `not v.strip()` with `PydanticCustomError("title_blank", "title must not be empty or only whitespace")`.
  Return the value unchanged (never strip it).
- `due_date: StrictStr | None = None`; validator (skip for `None`): `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v)`
  and `datetime.date.fromisoformat(v)` must succeed, else `PydanticCustomError("due_date_invalid", ...)`. Keep the
  string as sent. Do not use `\d` (matches non-ASCII digits) or `re.match` with `$`.
- Leave `extra` at Pydantic's default `"ignore"`.
- `Task` (response, schema name `Task`): `id: str`, `title: str`, `due_date: str | None` (required, nullable).
- Unit tests: every accepted and rejected value in the design's contract table, validated through
  `TaskCreate.model_validate(...)`, asserting the error `loc` per field and that both fields error together.

**Done when:** the unit tests pass and `devbox run quality` is green; the acceptance tests need t3.

## t2 — Add thread-safe in-memory TaskStore

**Files:** src/task_api/tasks/store.py, tests/test_unit_task_store.py
**Covers:** AC-001.4, AC-001.10, AC-001.11, AC-001.13, AC-001.16
**Goal:** one process-wide list of tasks with unique ids, kept in creation order, safe under concurrent requests.

**Implementation notes:**
- `TaskRecord`: frozen, slotted dataclass `id: str, title: str, due_date: str | None`. No import from `models.py`.
- `TaskStore.__init__`: empty list and a `threading.Lock`.
- `add(title, due_date) -> TaskRecord`: `id = str(uuid.uuid4())`, append under the lock, return the record.
- `list() -> list[TaskRecord]`: a copy of the list under the lock, oldest first.
- Unit tests: a new store is empty; ids differ for equal titles; order is preserved; a concurrent `add` from several
  threads loses nothing.

**Done when:** the unit tests pass and `devbox run quality` is green.

## t3 — Wire POST/GET /tasks router, validation error handler and app store

**Files:** src/task_api/tasks/router.py, src/task_api/errors.py, src/task_api/main.py
**Covers:** AC-001.1 to AC-001.18
**Goal:** expose the contract over HTTP and make the error body match it exactly.

**Implementation notes:**
- `router.py`: `APIRouter(tags=["tasks"])`; `get_task_store(request) -> TaskStore` returns
  `request.app.state.task_store`; sync handlers `create_task` (`POST /tasks`, `status_code=201`,
  `response_model=Task`) and `list_tasks` (`GET /tasks`, `response_model=list[Task]`, no query parameters).
  Map `TaskRecord` to `Task`. No `response_model_exclude_none`.
- Log `task_created` with `task_id` via structlog in `create_task` (no title in the log).
- `errors.py`: `validation_exception_handler(request, exc)`; rewrite each error with `type == "json_invalid"` to
  `loc = ("body",)`, build a new `RequestValidationError(errors, body=exc.body)` and return
  `fastapi.exception_handlers.request_validation_exception_handler(request, new_exc)`.
- `main.py`: `app.state.task_store = TaskStore()` right after the app is created, `app.include_router(router)`,
  `app.add_exception_handler(RequestValidationError, validation_exception_handler)`. Leave the existing endpoints,
  middleware and the Dockerfile untouched.
- Check `/openapi.json` lists `post` and `get` under `/tasks` and `components.schemas.Task`.

**Done when:** all acceptance tests for AC-001.1 to AC-001.18 pass (they reset `app.state.task_store` per the design's
test seam), the existing health/metrics/tracing tests still pass, and `devbox run ci` is green.
