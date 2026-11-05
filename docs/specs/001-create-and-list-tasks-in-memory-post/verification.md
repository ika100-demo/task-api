# Verification — 001 Create and list tasks in memory (POST /tasks, GET /tasks)

**Result:** pass
**Commit:** 9fc6e94 · **Base:** d1706c4 · **Trace:** 18/18 criteria named by tests (7/7 smoke criteria have a smoke test)

Test run (phase 3): `devbox run ci` green, 80 passed, 9 skipped (smoke, no `SMOKE_BASE_URL`), coverage 97%. Acceptance tests are unchanged since the red commit `5388570` (`git diff 5388570..HEAD -- tests/` only adds the two unit-test files).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_task_minimal`, `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` | `src/task_api/tasks/router.py:24`, `src/task_api/tasks/models.py:43`, `src/task_api/tasks/store.py:21` | asserts 201, exact key set `{id,title,due_date}`, non-empty string id, `due_date is None` |
| AC-001.2 | met | `tests/test_tasks.py::test_null_due_date_extra_field` (both payloads) | `src/task_api/tasks/models.py:14-18` (Pydantic default `extra="ignore"`, `due_date ... = None`) | asserts 201, `due_date` null, `colour` absent |
| AC-001.3 | met | `tests/test_tasks.py::test_create_task_with_due_date`, `tests/test_smoke_tasks.py::test_smoke_ac_001_3_create_task_with_due_date` | `src/task_api/tasks/models.py:27-40` | string returned as sent |
| AC-001.4 | met | `tests/test_tasks.py::test_ids_are_unique`, `tests/test_smoke_tasks.py::test_smoke_ac_001_4_ids_differ` | `src/task_api/tasks/store.py:21` (`uuid.uuid4()`) | same title used twice, as stated |
| AC-001.5 | met | `tests/test_tasks.py::test_invalid_title_rejected` (8 cases: missing, `""`, `"   "`, `"\t\n"`, U+00A0+U+3000, `42`, `null`, `["x"]`), `tests/test_smoke_tasks.py::test_smoke_ac_001_5_blank_title_rejected` | `src/task_api/tasks/models.py:17` (`StrictStr`), `src/task_api/tasks/models.py:20-25` (`not v.strip()`) | asserts 422, `loc[-1]=="title"`, list unchanged; the "before" list is always empty in the fresh store, but any stored task would still change it |
| AC-001.6 | met | `tests/test_tasks.py::test_non_object_body_rejected` (`[]`, `"text"`, `not json{`) | `src/task_api/errors.py:13-21`, registered at `src/task_api/main.py:28` | asserts an entry with `loc == ["body"]` and list unchanged; json_invalid offset is rewritten to `("body",)` |
| AC-001.7 | met | `tests/test_tasks.py::test_invalid_due_date_rejected` (all 7 values from the criterion), `tests/test_smoke_tasks.py::test_smoke_ac_001_7_bad_due_date_rejected` | `src/task_api/tasks/models.py:11`, `src/task_api/tasks/models.py:27-40` | `fullmatch` with ASCII `[0-9]` plus `date.fromisoformat`; `StrictStr` rejects `42`; `""` fails the regex |
| AC-001.8 | met | `tests/test_tasks.py::test_both_fields_invalid` | `src/task_api/tasks/models.py:20-40` (independent field validators) | asserts both `title` and `due_date` appear as last `loc` element |
| AC-001.9 | met | `tests/test_tasks.py::test_title_length_limit` | `src/task_api/tasks/models.py:17` (`Field(max_length=200)`, code points, untrimmed value) | 201 × ASCII / `ä` / emoji / space rejected with list unchanged; 200 × ASCII / `ä` / emoji accepted and echoed unchanged |
| AC-001.10 | met | `tests/test_tasks.py::test_list_empty` | `src/task_api/tasks/router.py:32-35`, `src/task_api/tasks/store.py:16-18` | |
| AC-001.11 | met | `tests/test_tasks.py::test_list_in_creation_order` | `src/task_api/tasks/store.py:23`, `src/task_api/tasks/store.py:26-28` | asserts list equals the three create responses in order and exact key set |
| AC-001.12 | met | `tests/test_tasks.py::test_list_ignores_query_params` | `src/task_api/tasks/router.py:33` (no query parameters declared) | two tasks so that `limit=1` being honoured would be detected |
| AC-001.13 | met | `tests/test_tasks.py::test_fresh_instance_is_empty` | `src/task_api/main.py:25` (store created at import, in-memory only), `src/task_api/tasks/store.py:16-18` | uses the design's test seam (new `TaskStore` on `app.state`) instead of a real process restart; acceptable because the store has no persistence by construction |
| AC-001.14 | met | `tests/test_tasks.py::test_past_and_today_due_dates` | `src/task_api/tasks/models.py:27-40` (no range check) | past and today's date both asserted |
| AC-001.15 | met | `tests/test_tasks.py::test_title_not_trimmed` | `src/task_api/tasks/models.py:25` (returns `v` unchanged), `src/task_api/tasks/router.py:27` | asserted in create response and in `GET /tasks` |
| AC-001.16 | met | `tests/test_tasks.py::test_repeated_gets_include_task`, `tests/test_smoke_tasks.py::test_smoke_ac_001_16_repeated_list_includes_task` | `src/task_api/main.py:25` (one process-wide store), `src/task_api/tasks/store.py:18,22,27` (lock) | 10 GETs, each 200 and containing the task |
| AC-001.17 | met | `tests/test_tasks.py::test_openapi_and_existing_endpoints`, `tests/test_smoke_tasks.py::test_smoke_ac_001_17_openapi_describes_tasks` | `src/task_api/tasks/router.py:24,32`, `src/task_api/tasks/models.py:43-48`, `src/task_api/main.py:38-59` (probes unchanged in the diff) | asserts `post`/`get` under `/tasks`, `Task` properties exactly `{id,title,due_date}`, health/ready/ping bodies and metrics 200 |
| AC-001.18 | met | `tests/test_tasks.py::test_other_methods_not_allowed` (DELETE, PUT) | `src/task_api/tasks/router.py:24,32` (only POST and GET routed; FastAPI default 405) | asserts 405 and list unchanged with one existing task |

## Non-goals

- No persistence or database: the store is a list in memory (`src/task_api/tasks/store.py:17`). ✔
- No `/tasks/{id}` routes; no filtering, sorting or paging (`src/task_api/tasks/router.py`). ✔
- No auth, users or ownership. ✔
- No `--workers` or replica change: Dockerfile and gitops untouched (not in the diff). ✔
- No idempotency logic, no size limit on the store. ✔
- No `Location` header, no extra fields on `Task` (`src/task_api/tasks/models.py:43-48`). ✔

## Deviations from the plan

- `tests/test_tasks.py` and `tests/test_smoke_tasks.py` changed but are in no task's `files`: these are the acceptance and smoke tests written in the red commit `5388570` before the build, as the process requires. Acceptable.
- `src/task_api/tasks/store.py:21` generates the UUID before taking the lock, while the design comment says "id = str(uuid.uuid4()); under lock". `uuid.uuid4()` is thread-safe and only the append needs the lock. Acceptable.
- `src/task_api/main.py:30` carries `# type: ignore[arg-type]` on the handler registration and `router.py:25,33` carry `# noqa: B008` for `Depends`. Tooling annotations only, no behaviour change. Acceptable.
- All three tasks t1, t2 and t3 are `done: true`; every other touched file is in a task's `files`.

## Contract

Matches `design.md`: task object `{id, title, due_date}` with required-nullable `due_date`; `POST /tasks` 201 / 422 with FastAPI's standard `detail` body, field `loc` `["body", "<field>"]`, non-object or invalid JSON body `loc` `["body"]`; `GET /tasks` 200 bare array in creation order, query parameters ignored; 405 for other methods; `/openapi.json` lists the operations and `components.schemas.Task`; existing endpoints unchanged; `task_created` is logged with `task_id` only, no title (`src/task_api/tasks/router.py:28`). ✔
