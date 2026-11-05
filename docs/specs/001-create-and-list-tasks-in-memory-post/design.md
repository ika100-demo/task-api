# Design — 001 Create and list tasks in memory (POST /tasks, GET /tasks)

## Decisions

- **New package `task_api.tasks`** (models, store, router) instead of growing `main.py`: `main.py` stays the app
  assembly point (middleware, probes, routers), the feature lives in one place later specs extend (`/tasks/{id}`).
- **Validation in Pydantic, strict and string-based.** FastAPI validates a body model with `validate_python` on the
  decoded JSON, so lax types would coerce: a `datetime.date` field accepts `42` (Unix timestamp) and a plain `str`
  field is fine but `date` would also accept datetimes at midnight. Therefore `title` is `StrictStr` and `due_date`
  is `StrictStr | None` checked by a validator (ASCII `[0-9]{4}-[0-9]{2}-[0-9]{2}` via `re.fullmatch`, then
  `datetime.date.fromisoformat`). The value is stored and returned **as the string sent**, which is the canonical form
  once it passed both checks (AC-001.3, AC-001.7, AC-001.14).
- **Validator errors are raised as `pydantic_core.PydanticCustomError`**, not `ValueError`: a `ValueError` puts the
  exception object into the error's `ctx`, which is not JSON-serialisable in every FastAPI version. Custom errors keep
  the standard 422 body clean.
- **One `RequestValidationError` handler** registered on the app normalises FastAPI's invalid-JSON error
  (`type: "json_invalid"`, `loc: ["body", <char offset>]`) to `loc: ["body"]` as the contract requires (AC-001.6),
  then delegates to FastAPI's stock `request_validation_exception_handler`. Every other error passes through
  unchanged, so the body format stays FastAPI's standard one.
- **Store on `app.state.task_store`**, a `TaskStore` instance created in `main.py` at import time, read by the router
  through a dependency. A process-wide list guarded by a `threading.Lock` (sync route handlers run in the threadpool).
  `app.state` gives tests a seam for a fresh instance (AC-001.10, AC-001.13) without a module reload.
- **No ADR:** the in-memory, single-instance choice is explicitly temporary (spec non-goals) and owned by the system
  spec; nothing here outlives the feature. No new dependency.
- **Single process stays:** the Dockerfile `CMD` already runs one uvicorn process without `--workers`; it is not
  touched. The gitops entry sets no `replicas`, so one replica runs; no gitops change.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/task_api/tasks/__init__.py` | package marker, re-exports nothing | new |
| `src/task_api/tasks/models.py` | `TaskCreate` (request), `Task` (response) Pydantic models and their validators | new |
| `src/task_api/tasks/store.py` | `TaskRecord` dataclass, `TaskStore` (thread-safe append + list) | new |
| `src/task_api/tasks/router.py` | `APIRouter` with `POST /tasks`, `GET /tasks`; `get_task_store` dependency | new |
| `src/task_api/errors.py` | `validation_exception_handler` (json_invalid → `loc: ["body"]`) | new |
| `src/task_api/main.py` | creates `app.state.task_store`, includes the router, registers the handler | changed |

### Interfaces

```python
# tasks/models.py
TITLE_MAX = 200
class TaskCreate(BaseModel):          # extra fields: ignored (Pydantic default "ignore")
    title: StrictStr                  # required; validator: not v.strip() -> PydanticCustomError("title_blank", ...)
                                      # Field(max_length=200) (len() = code points; checked on the untrimmed value)
    due_date: StrictStr | None = None # validator: re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v) and
                                      # date.fromisoformat(v) succeeds, else PydanticCustomError("due_date_invalid", ...)
class Task(BaseModel):                # OpenAPI schema name "Task"
    id: str
    title: str
    due_date: str | None              # required-nullable: always serialised, null when absent

# tasks/store.py
@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: str; title: str; due_date: str | None
class TaskStore:
    def add(self, title: str, due_date: str | None) -> TaskRecord   # id = str(uuid.uuid4()); under lock
    def list(self) -> list[TaskRecord]                              # copy, creation order; under lock

# tasks/router.py
router = APIRouter(tags=["tasks"])
def get_task_store(request: Request) -> TaskStore                    # request.app.state.task_store
@router.post("/tasks", status_code=201, response_model=Task)
def create_task(body: TaskCreate, store: TaskStore = Depends(get_task_store)) -> Task
@router.get("/tasks", response_model=list[Task])
def list_tasks(store: TaskStore = Depends(get_task_store)) -> list[Task]

# errors.py
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response
```

Notes that make the contract hold:

- `title` uses Python's `str.strip()`, which strips all Unicode whitespace (`\t`, `\n`, U+00A0, U+3000, ...)
  (AC-001.5). The length check uses the value as sent, so `" " * 201` fails on length and `"  Buy milk  "` is stored
  untrimmed (AC-001.9, AC-001.15).
- Both fields are validated independently, so `{"title": "", "due_date": "tomorrow"}` yields two `detail` entries
  (AC-001.8). A missing `title` yields Pydantic's `missing` entry with `loc: ["body", "title"]`.
- No `response_model_exclude_none` / `exclude_unset`: `due_date: null` must be present (AC-001.1).
- `GET /tasks` declares no query parameters; FastAPI ignores unknown ones (AC-001.12).
- `405` for `PUT`/`DELETE /tasks` is FastAPI's default once only GET and POST are routed (AC-001.18).
- Nothing is stored unless validation passed: the handler runs only after FastAPI validated the body (AC-001.5 to
  AC-001.9 "list unchanged").
- Log one structured event `task_created` with `task_id` (never the title: user content).

## Contract

Binding as written in the spec's "Contract" section; restated here as the testers' checklist.

**Task object** (OpenAPI schema `Task`): exactly `{"id": string (UUID4, non-empty), "title": string, "due_date": string "YYYY-MM-DD" | null}`. No other fields.

**`POST /tasks`**, body `application/json` object:

| Field | Required | Accepted | Rejected (422, `loc` ends with the field) |
|---|---|---|---|
| `title` | yes | JSON string, 1..200 code points, not only whitespace, returned untrimmed | missing, `null`, non-string (`42`, `["x"]`), `""`, whitespace-only, > 200 code points |
| `due_date` | no | absent, `null`, a real calendar date `YYYY-MM-DD` (past, today, future) | `""`, `"31.12.2026"`, `"2026-02-30"`, `"2026-1-5"`, `"2026-12-31T10:00:00"`, `"tomorrow"`, `42` |

Unknown fields are ignored and never echoed.

- `201` → the task object.
- `422` → `{"detail": [{"loc": [...], "msg": str, "type": str, ...}]}` (FastAPI standard; entries may carry `input`/`ctx`, callers must not depend on `msg`/`type` text). Field error: `loc == ["body", "<field>"]`. Body not a JSON object (array, string, number) or not valid JSON: an entry with `loc == ["body"]`. Empty body: entry with `loc == ["body"]` (type `missing`).
- `405` for any other method on `/tasks`.

**`GET /tasks`**: `200` → JSON array of task objects, creation order, oldest first; `[]` when empty; query parameters ignored.

**Unchanged:** `GET /health` → `{"status": "ok"}`, `GET /ready` → `{"status": "ready"}`, `GET /ping` → `{"pong": "task-api"}`, `GET /metrics` (Prometheus text). `/openapi.json` lists `post` and `get` under `paths["/tasks"]` and `components.schemas.Task` with properties `id`, `title`, `due_date`.

### Test seam (for acceptance tests)

A fresh, empty instance (AC-001.10, AC-001.13) is obtained without restarting the process by replacing the store:

```python
from task_api.main import app
from task_api.tasks.store import TaskStore
app.state.task_store = TaskStore()
```

Acceptance tests should reset the store this way per test (e.g. an autouse fixture) so tests are order-independent.

## Data

In memory only: `TaskStore._tasks: list[TaskRecord]`, `TaskStore._lock: threading.Lock`. No limit on size (non-goal). Lost on restart by construction (AC-001.13).

## Risks

- A body that is not valid UTF-8 makes FastAPI answer `400 "There was an error parsing the body"` before any
  validation handler runs. The contract's "not valid JSON" cases are text, which decodes; accepted as a known gap.
- Single instance only: a second replica or worker splits the list (spec non-goal). The Dockerfile and the gitops
  entry already guarantee one process; any future change there breaks AC-001.16.
