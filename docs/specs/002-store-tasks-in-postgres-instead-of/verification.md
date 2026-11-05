# Verification — 002 Store tasks in Postgres instead of memory

**Result:** pass
**Commit:** c90a16d · **Base:** f560cac · **Trace:** 14/14 criteria named by tests (smoke: AC-002.8, AC-002.9)

Test run: `devbox run ci` green (102 passed, 11 skipped smoke tests without `SMOKE_BASE_URL`, coverage 97 %,
pip-audit / detect-secrets / bandit clean). The acceptance tests (`tests/test_tasks_postgres.py`,
`tests/test_smoke_postgres.py`, `tests/conftest.py`, `tests/test_tasks.py`) have not changed since the red commit
`b19e7b8`; the only test file the coders changed afterwards is `tests/test_unit_task_store.py` (t1 owns it).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_tasks_postgres.py::test_restart_keeps_tasks` | `src/task_api/tasks/store.py:82-107`, `src/task_api/main.py:37-40` | The first store is closed, then a new `create_app(TaskStore(url))` runs on the same database. The list equals both create responses exactly: untrimmed `"  Buy milk  "`, `due_date` `null` and `"2026-12-31"`. `date.isoformat()` makes the date round trip lossless (`store.py:106`). |
| AC-002.2 | met | `tests/test_tasks_postgres.py::test_redeploy_keeps_order_and_new_ids` | `src/task_api/tasks/store.py:84,102` | Checks the list is exactly `[a, b, c]` and that C's id is not A's or B's. Ids are `uuid4` (`store.py:84`), order comes from `ORDER BY seq` (`store.py:102`). |
| AC-002.3 | met | `tests/test_tasks_postgres.py::test_rapid_creates_keep_response_order` | `src/task_api/tasks/store.py:74-75,102` | 20 back-to-back creates; the list ids equal the `201` response order. Order uses the identity `seq`, not a timestamp. |
| AC-002.4 | met | `tests/test_tasks_postgres.py::test_post_while_db_down_is_503_and_stores_nothing`, `::test_post_unreachable_from_start_is_503` | `src/task_api/tasks/store.py:15-20,86-94`, `src/task_api/errors.py:23-26`, `src/task_api/main.py:47-50` | Checks the exact body and a time under 5 s. After the container restarts, no task titled "Lost task" is in the list. |
| AC-002.5 | met | `tests/test_tasks_postgres.py::test_get_while_db_down_is_503`, `::test_store_raises_unavailable_on_closed_port` | `src/task_api/tasks/store.py:97-104`, `src/task_api/errors.py:26` | A task is stored before the outage; `GET` then answers `503` with the exact body in under 5 s, so it is never `200`/`[]`. |
| AC-002.6 | met | `tests/test_tasks_postgres.py::test_locked_table_is_503[get]`, `[post]` | `src/task_api/tasks/store.py:53` (`statement_timeout=2000`), `:46` (checkout 2 s), `:93-94` | A second session holds `ACCESS EXCLUSIVE`. Both methods answer `503` with the exact body in under 5 s, and "during lock" is absent afterwards. `QueryCanceled` is an `OperationalError`, so it is mapped. |
| AC-002.7 | met | `tests/test_tasks_postgres.py::test_invalid_body_is_422_while_db_down[payload0]`, `[payload1]` | `src/task_api/tasks/router.py:31-32` (FastAPI validates `TaskCreate` before the handler) | Store on a closed port. Both cases are `422`, and the last `loc` element names `title` / `due_date`. |
| AC-002.8 | met | `tests/test_tasks_postgres.py::test_openapi_lists_503`; smoke `tests/test_smoke_postgres.py::test_smoke_ac_002_8_openapi_lists_503` | `src/task_api/tasks/router.py:17-19,31,39` | POST has `201`/`422`/`503`; GET has `200`/`503`; the schema is `ErrorMessage` (`errors.py:19-20`). |
| AC-002.9 | met | `tests/test_tasks_postgres.py::test_ready_and_health_ok`; smoke `tests/test_smoke_postgres.py::test_smoke_ac_002_9_ready_and_health_ok` | `src/task_api/main.py:52-64`, `src/task_api/tasks/store.py:109-115` | `/ready` runs `SELECT 1` and returns `{"status": "ready"}`; `/health` never touches the store. |
| AC-002.10 | met | `tests/test_tasks_postgres.py::test_ready_503_when_db_goes_down` | `src/task_api/main.py:57-63`, `src/task_api/tasks/store.py:112` (checkout `timeout=1.0`) | Checks `503`, `{"status": "not ready"}`, a time under 3 s, and `/health` still `200` afterwards. |
| AC-002.11 | met | `tests/test_tasks_postgres.py::test_recovers_without_restart` | `src/task_api/tasks/store.py:47-48` (`reconnect_timeout=10`, `check_connection`) | Same app and store throughout. `/ready` is polled up to 30 s after the database is back; the task from before the outage is listed and a POST answers `201`. |
| AC-002.12 | met | `tests/test_tasks_postgres.py::test_starts_without_db_and_recovers` | `src/task_api/tasks/store.py:42-57` (`open(wait=False)`), `:65-80` (lazy schema on first checkout) | Table dropped, database stopped, then the instance is built. Checks `/health` `200`, `/ready` `503`, then after recovery `/ready` `200` within 30 s, `GET` `[]` and POST `201`. |
| AC-002.13 | met | `tests/test_tasks_postgres.py::test_two_instances_share_one_list` | `src/task_api/tasks/store.py:72` (advisory xact lock around DDL), `:102` | Two apps with separate pools create 20 tasks concurrently (10 each). Ten alternating GETs each return 20 distinct ids in the same order. |
| AC-002.14 | met | `tests/test_tasks.py` (AC-001.1 to AC-001.12, AC-001.14 to AC-001.18, all through the Postgres `client` fixture, `tests/conftest.py:73-83`), `tests/test_tasks_postgres.py::test_spec_001_runs_on_the_database` | `src/task_api/tasks/store.py`, `src/task_api/tasks/router.py` (handler bodies unchanged) | The autouse `_fresh_store` depends on `client`, so every spec 001 test runs on the truncated database. The AC-001.13 test was removed as the spec says. |

## System context (binding notes)

- psycopg 3 + psycopg_pool: `pyproject.toml` (`psycopg[binary]>=3.3.8`, `psycopg-pool>=3.3.3`), lockfile updated; testcontainers is a dev extra. ✔
- `DATABASE_URL` is read in `src/task_api/main.py:40`. An unset or empty value leaves the store unconfigured (`store.py:39-41`, logs `task_store_unconfigured` at error level), so the routes answer `503` and the process does not crash. ✔
- The schema is created by the service on the first successful checkout, not at import or startup (`store.py:65-80`, called from `add`/`list` only), with the DDL from the design. ✔
- Order is by the identity `seq`; no timestamp column exists. ✔
- Tests use a real Postgres through testcontainers (`tests/conftest.py:47-56,86-141`); there is no SQLite. ✔
- `/ready` runs `SELECT 1` (`store.py:113`); `/health` is independent of the database. ✔
- The process starts while the database is down because the pool opens with `wait=False` (`store.py:57`). ✔
- The `503` body is exactly `{"detail": "The task store is unavailable."}` (`errors.py:26`), with no `Retry-After`. ✔
- Timeouts: connect 2 s, checkout 2 s, statement 2 s, `/ready` checkout 1 s (`store.py:46,52-53,112`). ✔

## Non-goals

None of the excluded features was built: no migration tool (only `CREATE TABLE IF NOT EXISTS`), no data import from memory, no caching or queued writes during an outage, no `Retry-After` header or extra `503` fields, no retry of a `POST` inside the API, no idempotent create, no change to the task object, validation, `422` or order, and no single-task, filter or paging endpoints. ✔

## Deviations from the plan

- `tests/conftest.py`, `tests/test_tasks.py`, `tests/test_tasks_postgres.py`, `tests/test_smoke_postgres.py`, plus `pyproject.toml`/`uv.lock` for the `testcontainers` dev dependency, are in no task's `files`. They were changed in the testers' red commit `b19e7b8`, as the plan states. Acceptable.
- `docs/adr/001-postgres-task-storage.md` and the spec, design and plan documents are design-phase artefacts and are in no task's `files`. Acceptable.
- Both tasks are `done: true`. Coder commits `f389def` and `83c269c` stay inside their tasks' `files`. ✔
- `TaskStore.__init__(conninfo: str | None = None)` has a default where the design shows none. This is harmless and backward compatible. Acceptable.
- `task_store_unavailable_handler` logs at `warning` level (`errors.py:25`); the design gives no level for this event and logs only the class name, as required. For the unconfigured case `exc.__cause__` is `None`, so it logs `error="NoneType"`. This is cosmetic. Acceptable.

## Contract

Matches `design.md`:
- the `503` body and status on both task routes;
- `/ready` `200 {"status": "ready"}` / `503 {"status": "not ready"}` with `503` declared in OpenAPI (`main.py:57`);
- `/health` `{"status": "ok"}`;
- the OpenAPI `503` with the `ErrorMessage` schema;
- `create_app(store)` seam, lifespan closing the store (`main.py:31-34`);
- the pool parameters exactly as in the design's Interfaces (`store.py:42-57`);
- static SQL only, and no conninfo or titles logged. ✔
