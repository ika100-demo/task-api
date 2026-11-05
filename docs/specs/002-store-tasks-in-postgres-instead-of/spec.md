---
spec_id: 002-store-tasks-in-postgres-instead-of
title: Store tasks in Postgres instead of memory, answer 503 and report not ready while the database is down
status: building
priority: P1
shape: service-python
parent: ika100-demo/taskboard-gitops:002-tasks-in-postgres-and-a-web-ui
---

# 002 — Store tasks in Postgres instead of memory, answer 503 and report not ready while the database is down

## Problem

Spec 001 gave the taskboard a task API that can create and list tasks, but the tasks live only in the task API's memory: every restart or redeploy throws away the whole board (AC-001.9), and the API has to run as a single instance (AC-001.12). The only way to use the board is to send raw HTTP requests, so nobody who is not a developer can use it. This feature keeps tasks in a Postgres database so they survive restarts and redeploys, and adds a web UI where people can see the board and add tasks to it. The task API contract from spec 001 (paths, fields, validation, `422` errors, oldest-first bare array) stays as it is. Only the in-memory consequences change. This spec supersedes AC-001.9 and the single-instance constraint of AC-001.12 and of spec 001's non-goals.

## System context

Slice of the system plan `002-tasks-in-postgres-and-a-web-ui` in `ika100-demo/taskboard-gitops` for `task-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-002.1** Given a task was created with `POST /tasks`, when the task API restarts, then `GET /tasks` still returns that task with the same `id`, `title` and `due_date` as its create response (supersedes AC-001.9).
- **AC-002.2** Given tasks A and B were created, the task API was then redeployed with a new version, and task C was created after that, when a caller sends `GET /tasks`, then the response is `200` with exactly A, B and C in creation order (A, B, C), and C's `id` differs from A's and B's.
- **AC-002.3** Given the database is unreachable, when a caller sends `POST /tasks` with a valid body or `GET /tasks`, then the response is `503` with a JSON error saying the task store is unavailable (never `201` and never an empty list `[]`), and once the database is reachable again no task from the failed `POST` appears in `GET /tasks`.
- **AC-002.4** Given the database is unreachable, when the task API's readiness endpoint is called, then it answers with a non-`200` status, and it answers `200` again within 30 seconds after the database is reachable again, without the task API being restarted.
- **AC-002.5** Given the task API runs as 2 instances and a task was created, when a caller sends `GET /tasks` 10 times in a row, then every response includes that task (one shared list regardless of the number of instances; supersedes the single-instance constraint of AC-001.12).
- **AC-002.6** Given spec 001's criteria AC-001.1 to AC-001.8, AC-001.10 and AC-001.11, when they are run against the task API backed by the database, then they all still pass (the API contract is unchanged; for AC-001.7 "since the task API started" now reads "in this environment's database").

### Contract

Two contracts: `task-api` for any HTTP caller (the web app's server among them), and the web app's own
`/api/tasks` route between its browser code and its server. The browser never calls `task-api`.

### task-api (unchanged from spec 001 except the `503`)

Base URL: in the namespace `http://task-api` (Service port 80, container 8080); in dev also through the Gateway at
`http://task-api.taskboard-dev.localhost`. All bodies are JSON (`Content-Type: application/json`, UTF-8).

Task object:

| Field | Type | Notes |
|---|---|---|
| `id` | string | non-empty, assigned by the server, unique among all tasks in the environment's database; opaque (UUID4 string) |
| `title` | string | exactly as sent, untrimmed, 1 to 200 characters (Unicode code points), not only whitespace |
| `due_date` | string or `null` | `YYYY-MM-DD` calendar date, or `null` when none was given |

No other fields are returned.

`POST /tasks`: request object with `title` (required, JSON string, not empty or only whitespace, at most 200
characters as sent) and `due_date` (optional; absent or `null` = none; else exactly `YYYY-MM-DD` and a real
calendar date, past dates accepted). Unknown fields are ignored. Responses:

- `201` with the created task object; it is durably stored when the response is sent.
- `422` for invalid input (format in "Errors"), checked before the database is touched; nothing is stored.
- `503` when the task store is unavailable; nothing is stored.

`GET /tasks`: no parameters. `200` with a bare JSON array of task objects in creation order, oldest first; `[]`
only when the database holds no task. `503` when the task store is unavailable (never `[]` in that case).

`GET /ready`: `200` `{"status": "ready"}` when a `SELECT 1` on the database succeeds; `503`
`{"status": "not ready"}` otherwise. `GET /health`: always `200` while the process runs (does not check the
database). `/metrics`, `/ping`, `/docs`, `/openapi.json` unchanged; `/openapi.json` lists the `503` on both
task operations.

### taskboard-web internal route (same origin, browser to web server)

`POST /api/tasks` on the web app, body `{"title": <string>, "due_date": <"YYYY-MM-DD" or null>}`, forwarded
unchanged to `POST {TASK_API_URL}/tasks`:

- task-api `201`: answer `201` with the task object as received.
- task-api `422`: answer `422` with task-api's body as received (the client shows the title message when an entry's
  `loc` ends in `"title"`, choosing the text by its own length/whitespace rule, and "The task could not be saved.
  Try again." for any other `422`).
- anything else, a connection error or a timeout: answer `502` `{"detail": "The task could not be saved."}`.

The page `/` itself reads `GET {TASK_API_URL}/tasks` on the server; there is no `GET /api/tasks`.

### Errors

`task-api` error formats:

- `422`: FastAPI's validation body `{"detail": [{"loc": ["body", "title"], "msg": "...", "type": "..."}]}`; the last
  `loc` element names the field (`"title"` or `"due_date"`); `["body"]` for a body that is not a JSON object. `msg`
  and `type` are informative only.
- `503`: `{"detail": "The task store is unavailable."}` (exactly this string) for `POST /tasks` and `GET /tasks`.
- `404`/`405`: FastAPI defaults `{"detail": "..."}`. `500` only for an unexpected fault unrelated to the database.

How a caller treats a response the contract does not list (any other `4xx`/`5xx`, a body that is not the expected
JSON shape, a `200` from `GET /tasks` that is not an array of task objects): the call failed. It does not assume a
task was created and does not show a partial list. For `taskboard-web`: a failed `GET /tasks` (including `503`)
renders "Tasks could not be loaded. Try again later."; a failed `POST` renders "The task could not be saved. Try
again." with the inputs kept. `POST /tasks` is not idempotent: neither the web server nor the browser retries it
automatically; after a timeout the task may or may not exist, and the user's next page load shows the truth.

Gateway or Service failures (`502`/`503`/`504` without the JSON body, connection refused) count as failures in the
same way.

### Timeouts

- `task-api` to Postgres: connect timeout 2 s, pool checkout timeout 2 s, `statement_timeout` 2 s. When the
  database is down or slow, `POST /tasks` and `GET /tasks` answer `503` within 5 s; `/ready` answers `503` within
  3 s. The pool keeps retrying connections in the background; no request blocks longer than these limits, and the
  process does not exit.
- Readiness recovery: `/ready` reflects the database on every call, so it returns to `200` at the first probe after
  the database is back (kubelet period 10 s, under the 30 s of AC-002.4).
- `taskboard-web` server to `task-api`: 6 s total per request (`AbortSignal.timeout(6000)`), above `task-api`'s own
  5 s worst case so a `503` arrives as a `503` and not as a timeout. No retry for `POST`; no retry for the page's
  `GET` either (the page renders the load-error message; the user reloads).
- Browser to `taskboard-web` `/api/tasks`: 10 s (`AbortSignal.timeout(10000)`); on timeout the save-error message
  is shown and the inputs are kept.
- When `task-api` is down, the web app keeps serving `/` (with the load-error message) and stays ready; its probes
  never call `task-api`.

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Replace the in-memory TaskStore (src/task_api/tasks/store.py) with a Postgres store behind the same
add()/list() interface; keep router.py and models.py and the spec 001 tests (adapt only the store fixture).
Driver: psycopg 3 with psycopg_pool (add "psycopg[binary]" and "psycopg-pool" through devbox/uv, never pip).
Connection: read DATABASE_URL (set by the gitops-app from the postgres resource; PG* vars are also present).
Schema: created by the service itself with idempotent DDL the first time a connection succeeds (not only
at import/startup, so a pod started while the database is down recovers without a restart), e.g.
tasks(seq bigint generated always as identity primary key, id uuid not null unique, title text not null,
due_date date null). Order GET /tasks by seq; never by a timestamp.
The process must start (and /health answer 200) while the database is down; only /ready and the task
routes report it. The single-uvicorn-process constraint of spec 001 is lifted.
Tests run against a real Postgres (testcontainers-python, Docker), not SQLite; the "database down" cases
stop the container or point the pool at a closed port. Spec 001's in-memory restart test (AC-001.9) is
superseded: delete it or turn it into the AC-002.1 test (new app instance, same database).

## Stories

As a taskboard user, I want the tasks I created to still be there after the task API restarts or is redeployed, so that the board is a reliable place to write down what I have to do.

As a caller of the task API (the web app's server among them), I want a clear `503` saying the task store is unavailable while the database is down, instead of an empty list or a fake success, so that I never show a wrong board or believe a task was saved when it was not.

As the operator of the taskboard, I want the task API to report itself not ready while the database is down, to recover on its own when the database is back, and to run as more than one instance, so that traffic only goes to instances that can serve it and no restart or single-instance limit is needed.

## Acceptance criteria

- **AC-002.1** Given tasks `{"title": "  Buy milk  "}` and `{"title": "File taxes", "due_date": "2026-12-31"}` were created through one task API instance, when that instance is stopped and a new instance is started against the same database, then `GET /tasks` on the new instance answers `200` with both tasks, each with the same `id`, `title` (untrimmed) and `due_date` (`null` for the first) as its create response. (system AC-002.1)
- **AC-002.2** Given tasks A and B were created through a first instance, that instance was replaced by a new instance on the same database, and task C was created through the new instance, when a caller sends `GET /tasks`, then the response is `200` with exactly A, B and C in that order, and C's `id` differs from A's and B's. (system AC-002.2)
- **AC-002.3** Given 20 tasks were created back to back as fast as the caller can send them, when a caller sends `GET /tasks`, then the 20 tasks are returned in exactly the order their `201` responses were received (order does not depend on clock resolution). (system AC-002.2)
- **AC-002.4** Given the database is unreachable, when a caller sends `POST /tasks` with `{"title": "Lost task"}`, then the response is `503` with the body exactly `{"detail": "The task store is unavailable."}` within 5 seconds, and once the database is reachable again `GET /tasks` contains no task titled `"Lost task"`. (system AC-002.3)
- **AC-002.5** Given the database is unreachable and held at least one task before, when a caller sends `GET /tasks`, then the response is `503` with the body exactly `{"detail": "The task store is unavailable."}` within 5 seconds, never `200` and never `[]`. (system AC-002.3)
- **AC-002.6** Given the database accepts connections but a query on the tasks does not complete (for example the task table is locked by another session), when a caller sends `GET /tasks` or `POST /tasks` with a valid body, then each answers `503` with the body exactly `{"detail": "The task store is unavailable."}` within 5 seconds, and a `POST` answered `503` stores no task. (system AC-002.3)
- **AC-002.7** Given the database is unreachable, when a caller sends `POST /tasks` with an invalid body (for example `{"title": ""}` or `{"title": "x", "due_date": "tomorrow"}`), then the response is `422` with the validation body of spec 001 naming the field, not `503` (input is checked before the database is touched). (system AC-002.3)
- **AC-002.8** Given the task API is running, when a caller requests `/openapi.json`, then both `POST /tasks` and `GET /tasks` list a `503` response in addition to their spec 001 responses. (system AC-002.3) (smoke)
- **AC-002.9** Given the database is reachable, when a caller sends `GET /ready` and `GET /health`, then both answer `200`, `/ready` with the body `{"status": "ready"}`. (system AC-002.4) (smoke)
- **AC-002.10** Given a running task API whose database becomes unreachable, when a caller sends `GET /ready`, then it answers `503` with the body `{"status": "not ready"}` within 3 seconds, while `GET /health` keeps answering `200` and the process keeps running. (system AC-002.4)
- **AC-002.11** Given the database became unreachable while the task API was running, when the database is reachable again, then without restarting the task API `GET /ready` answers `200` within 30 seconds, `GET /tasks` returns the tasks stored before the outage and `POST /tasks` with a valid body answers `201`. (system AC-002.4)
- **AC-002.12** Given an empty database without any task table and the database unreachable, when a task API instance is started, then the process starts, `GET /health` answers `200` and `GET /ready` answers `503`; and when the database then becomes reachable, without restarting the instance, `GET /ready` answers `200` within 30 seconds, `GET /tasks` answers `200` with `[]` and `POST /tasks` with a valid body answers `201`. (system AC-002.4)
- **AC-002.13** Given two task API instances on the same database, when 10 tasks are created through each instance concurrently and then `GET /tasks` is sent 10 times alternating between the two instances, then every response is `200` and contains all 20 tasks with 20 distinct `id` values, in the same order on both instances. (system AC-002.5)
- **AC-002.14** Given spec 001's criteria AC-001.1 to AC-001.12 and AC-001.14 to AC-001.18, when they are run against the task API backed by the database, then they all pass, with AC-001.10 read as "given the database holds no task" and AC-001.16 holding for any number of instances; AC-001.13 (a fresh instance returns `[]`) no longer applies and is replaced by AC-002.1. (system AC-002.6)

## Non-goals

- Moving tasks from the old in-memory store into the database (none survive a restart today).
- Versioned schema migrations or a migration tool; the service only creates its table when it is missing.
- Provisioning, backing up or restoring the database, and choosing its size; the system's gitops repo provides it.
- Serving cached or partial data while the database is down, or queueing writes to replay later.
- A `Retry-After` header or any other field on the `503` beyond `detail`.
- Retrying a failed `POST /tasks` inside the task API, and idempotent creation (a retried `POST` still creates a second task).
- Any change to the task object, the validation rules, the `422` format or the list order of spec 001.
- Reading, updating, completing or deleting a single task, and filtering, sorting or paging the list.

## Open questions

none

## Changelog

- 2026-11-05 created
- 2026-11-05 approved
- 2026-11-05 building
