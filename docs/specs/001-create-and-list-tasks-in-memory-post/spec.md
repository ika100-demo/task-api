---
spec_id: 001-create-and-list-tasks-in-memory-post
title: Create and list tasks in memory (POST /tasks, GET /tasks)
status: draft
priority: P1
shape: service-python
parent: ika100-demo/taskboard-gitops:001-create-and-list-tasks
---

# 001 — Create and list tasks in memory (POST /tasks, GET /tasks)

## Problem

The taskboard system has no tasks yet: the task API only answers health, readiness, metrics and documentation requests. A user can't write down something to do or look at what is already on the board. This first feature adds the core of the system, creating a task with a title and an optional due date and listing the tasks, so later features have something to build on. Tasks are kept only in memory for now.

## System context

Slice of the system plan `001-create-and-list-tasks` in `ika100-demo/taskboard-gitops` for `task-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given the task API is running, when a caller sends `POST /tasks` with `{"title": "Buy milk"}`, then the response is `201` with a JSON object holding a non-empty `id`, `"title": "Buy milk"` and `"due_date": null`.
- **AC-001.2** Given the task API is running, when a caller sends `POST /tasks` with `{"title": "File taxes", "due_date": "2026-12-31"}`, then the response is `201` and the returned task has `"due_date": "2026-12-31"`.
- **AC-001.3** Given two tasks created one after the other, when each create response is read, then the two `id` values are different.
- **AC-001.4** Given a request body with no `title`, a `title` that is not a string, or a `title` that is empty or only whitespace, when a caller sends `POST /tasks`, then the response is `422` with an error that names the `title` field, and no task is created (the list is unchanged).
- **AC-001.5** Given a `due_date` that is not a valid calendar date in `YYYY-MM-DD` form (for example `"31.12.2026"`, `"2026-02-30"`, `"tomorrow"` or `42`), when a caller sends `POST /tasks`, then the response is `422` with an error that names the `due_date` field, and no task is created.
- **AC-001.6** Given a `title` longer than 200 characters, when a caller sends `POST /tasks`, then the response is `422` with an error that names the `title` field, and no task is created; a title of exactly 200 characters is accepted.
- **AC-001.7** Given no task has been created since the task API started, when a caller sends `GET /tasks`, then the response is `200` with an empty JSON array `[]`.
- **AC-001.8** Given tasks A, B and C were created in that order, when a caller sends `GET /tasks`, then the response is `200` with a JSON array of exactly those three tasks in creation order (A, B, C), each with the same `id`, `title` and `due_date` as its create response.
- **AC-001.9** Given a task was created, when the task API restarts, then `GET /tasks` no longer returns it (tasks are held in memory only).
- **AC-001.10** Given a `due_date` in the past, for example `"2020-01-15"`, when a caller sends `POST /tasks` with `{"title": "Old errand", "due_date": "2020-01-15"}`, then the response is `201` and the returned task has `"due_date": "2020-01-15"`.
- **AC-001.11** Given a `title` with leading and trailing whitespace, for example `"  Buy milk  "`, when a caller sends `POST /tasks`, then the response is `201` and the title is returned exactly as sent (`"  Buy milk  "`) both in the create response and in `GET /tasks`.
- **AC-001.12** Given a task was created, when a caller sends `GET /tasks` 10 times in a row, then every response includes that task (all callers see one shared list; the task API runs as a single instance in every environment).

### Contract

The contract is between `task-api` and any HTTP caller (there is no other repo in this system yet). Base path: the
service root (in the cluster `http://task-api`, port 80 on the Service, 8080 in the container; in dev through the
Gateway at `http://task-api.taskboard-dev.localhost`). All bodies are JSON (`Content-Type: application/json`, UTF-8).

### Task object

| Field | Type | Notes |
|---|---|---|
| `id` | string | non-empty, assigned by the server, unique among the tasks of the running instance; opaque to callers (implementation: UUID4 as string) |
| `title` | string | exactly as sent, untrimmed, 1 to 200 characters, not only whitespace |
| `due_date` | string or `null` | calendar date `YYYY-MM-DD` (ISO 8601, no time, no zone), or `null` when none was given |

No other fields are returned.

### `POST /tasks`

Request body: a JSON object.

| Field | Required | Rule |
|---|---|---|
| `title` | yes | JSON string; after stripping whitespace (for the check only) at least 1 character; at most 200 characters as sent |
| `due_date` | no | absent or `null` means no due date; otherwise a JSON string matching exactly `YYYY-MM-DD` that is a real calendar date (past, today and future all accepted) |

Unknown extra fields are ignored. A body that is not a JSON object (or not valid JSON) is `422`.

Responses:

- `201 Created` with the created task object. No `Location` header is required.
- `422 Unprocessable Entity` for any invalid input (see "Errors"); nothing is stored.

### `GET /tasks`

No parameters (query parameters are ignored). Response `200 OK` with a bare JSON array of task objects in creation
order, oldest first; `[]` when there are none. Each element equals the create response of that task.

### Existing endpoints (unchanged)

`GET /health`, `GET /ready`, `GET /metrics`, `GET /ping`, and the FastAPI docs (`/docs`, `/openapi.json`) keep
their current behaviour. `/openapi.json` must describe the two new operations and the task object.

### Errors

Error format: FastAPI's standard validation error body, status `422`:

```json
{"detail": [{"loc": ["body", "title"], "msg": "<human-readable message>", "type": "<error type>"}]}
```

- `detail` is a non-empty array. Each entry's `loc` is the path to the offending field; for a field error the last
  element is the field name (`"title"` or `"due_date"`), which is how an error "names the field" (AC-001.4 to AC-001.6).
- A missing `title` yields an entry with `loc` `["body", "title"]`. When both fields are invalid, both are listed.
- A body that is not a JSON object yields an entry whose `loc` is `["body"]`.
- `msg` and `type` are informative; callers and tests must not depend on their exact text.

Other statuses: `405` for another method on `/tasks`, `404` for unknown paths (FastAPI defaults,
`{"detail": "..."}`). `500` only for an unexpected server fault.

A caller treats any status the contract does not list for an operation (any `5xx`, an unexpected `4xx`) as a failure
of that call: it does not assume a task was created and does not parse the body as a task. A `POST` that failed that
way or timed out may or may not have stored the task; the caller may check with `GET /tasks` before retrying, since
`POST /tasks` is not idempotent (a retry creates a second task).

### Timeouts

- Server side: both operations are in-memory and answer within 100 ms under normal load; no call made by
  `task-api` to anything else (it has no dependencies), so there is no downstream timeout or fallback.
- Callers: use a 5 s total timeout per `POST /tasks` and `GET /tasks` request (2 s to connect). On a timeout or a
  connection error the call has failed (see "Errors" for the non-idempotent `POST`); retry at most once for `GET`.
- When `task-api` is down or restarting, the Gateway or Service answers with a connection error or `502`/`503`;
  callers treat that as failure. After a restart the list is empty (AC-001.9): that is expected, not an error.
- Probes (`/health`, `/ready`) stay as they are; `/ready` needs no change because the store is ready at startup.

### Notes for this repo

FastAPI app in src/task_api/main.py; add the routes there or in a new router module next to it.
The store is one process-wide in-memory list guarded by a lock; no database, no new dependency.
Keep the Dockerfile CMD as a single uvicorn process (no --workers): a second worker would hold a
second list and break the shared list just as a second replica would.

## Stories

As a taskboard user, I want to create a task with a title and, if I like, a due date, so that I can write down what I have to do.

As a taskboard user, I want to see all tasks in the order I created them, so that I know what is on the board.

As a caller of the task API, I want invalid input rejected with an error that names the offending field, so that I can correct my request and nothing half-valid ends up on the board.

## Acceptance criteria

- **AC-001.1** Given the task API is running, when a caller sends `POST /tasks` with `{"title": "Buy milk"}`, then the response is `201` with a JSON object that has exactly the fields `id` (a non-empty string), `"title": "Buy milk"` and `"due_date": null`. (system AC-001.1) (smoke)
- **AC-001.2** Given the task API is running, when a caller sends `POST /tasks` with `{"title": "Buy milk", "due_date": null}` or with `{"title": "Buy milk", "colour": "red"}`, then the response is `201`, the task has `"due_date": null`, and the unknown field `colour` does not appear in the response. (system AC-001.1)
- **AC-001.3** Given the task API is running, when a caller sends `POST /tasks` with `{"title": "File taxes", "due_date": "2026-12-31"}`, then the response is `201` and the returned task has `"due_date": "2026-12-31"`. (system AC-001.2) (smoke)
- **AC-001.4** Given two tasks created one after the other with the same title, when each create response is read, then the two `id` values are different. (system AC-001.3) (smoke)
- **AC-001.5** Given a request body with no `title`, with `"title": ""`, with a title of only whitespace (`"   "`, or any Unicode whitespace such as `"\t\n"` or `"  "`), or with a non-string `title` (`42`, `null`, `["x"]`), when a caller sends `POST /tasks`, then for each case the response is `422`, the body's `detail` array has an entry whose `loc` ends with `"title"`, and `GET /tasks` returns the same list as before the request. (system AC-001.4) (smoke)
- **AC-001.6** Given a request body that is not a JSON object (a JSON array `[]`, a JSON string, or text that is not valid JSON), when a caller sends `POST /tasks`, then the response is `422` with a `detail` entry whose `loc` is `["body"]`, and `GET /tasks` is unchanged. (system AC-001.4)
- **AC-001.7** Given a `due_date` of `"31.12.2026"`, `"2026-02-30"`, `"tomorrow"`, `"2026-1-5"`, `"2026-12-31T10:00:00"`, `""` or `42`, when a caller sends `POST /tasks` with an otherwise valid title, then for each case the response is `422`, the `detail` array has an entry whose `loc` ends with `"due_date"`, and `GET /tasks` is unchanged; only an absent `due_date` or `null` means no due date. (system AC-001.5) (smoke)
- **AC-001.8** Given a body where both `title` and `due_date` are invalid, for example `{"title": "", "due_date": "tomorrow"}`, when a caller sends `POST /tasks`, then the response is `422` and `detail` has one entry naming `title` and one naming `due_date`. (system AC-001.5)
- **AC-001.9** Given a `title` of 201 characters (counted as Unicode code points, not bytes; whitespace counted, so 200 × `"ä"` or 200 emoji are 200 characters), when a caller sends `POST /tasks`, then the response is `422` with a `detail` entry whose `loc` ends with `"title"` and `GET /tasks` is unchanged; given a `title` of exactly 200 characters, the response is `201` and the title is returned unchanged. (system AC-001.6)
- **AC-001.10** Given no task has been created since the task API started, when a caller sends `GET /tasks`, then the response is `200` with the empty JSON array `[]`. (system AC-001.7)
- **AC-001.11** Given tasks A, B and C were created in that order, when a caller sends `GET /tasks`, then the response is `200` with a bare JSON array of exactly three task objects in the order A, B, C, each equal (same `id`, `title`, `due_date`, no other fields) to its create response. (system AC-001.8)
- **AC-001.12** Given tasks exist, when a caller sends `GET /tasks?limit=1&foo=bar`, then the response is the same as for `GET /tasks` (query parameters are ignored). (system AC-001.8)
- **AC-001.13** Given a task was created, when the task API is started anew (a fresh instance), then `GET /tasks` on it returns `[]`. (system AC-001.9)
- **AC-001.14** Given the task API is running, when a caller sends `POST /tasks` with `{"title": "Old errand", "due_date": "2020-01-15"}`, then the response is `201` and the returned task has `"due_date": "2020-01-15"`; the same holds for today's date. (system AC-001.10)
- **AC-001.15** Given the task API is running, when a caller sends `POST /tasks` with `{"title": "  Buy milk  "}`, then the response is `201` with `"title": "  Buy milk  "`, and the same untrimmed title appears for that task in `GET /tasks`. (system AC-001.11)
- **AC-001.16** Given a task was created, when a caller sends `GET /tasks` 10 times in a row, then every one of the 10 responses is `200` and includes that task. (system AC-001.12) (smoke)
- **AC-001.17** Given the task API is running, when a caller requests `/openapi.json`, then it describes `POST /tasks` and `GET /tasks` and the task object with the fields `id`, `title` and `due_date`; `GET /health`, `GET /ready`, `GET /ping` and `GET /metrics` answer as before this feature. (system AC-001.1) (smoke)
- **AC-001.18** Given the task API is running, when a caller sends `DELETE /tasks` or `PUT /tasks`, then the response is `405` and the task list is unchanged. (system AC-001.8)

## Non-goals

- Persistence: tasks are lost when the task API restarts; no database.
- Reading, updating, completing or deleting a single task (`GET/PUT/PATCH/DELETE /tasks/{id}`).
- Filtering, sorting, paging or searching the list.
- Users, ownership, authentication or permissions; every caller sees one shared list.
- Running more than one instance or worker of the task API (a second one would hold a second list).
- Idempotent creation: a retried `POST /tasks` creates a second task.
- Any limit on the number of tasks held.
- A `Location` header on `201`, and fields beyond `id`, `title` and `due_date` (no creation timestamp, no status).

## Open questions

- ~~Confirm: the 200-character limit counts Unicode characters, so an emoji or `ä` counts as one character regardless of its byte length.~~ Answered: yes, Unicode code points, not bytes; see AC-001.9.
- ~~Confirm: "only whitespace" means any Unicode whitespace, so a title of tabs, newlines or non-breaking spaces only is rejected like `"   "`.~~ Answered: yes; see AC-001.5.
- ~~Confirm: an empty string `""` as `due_date` is rejected with `422` rather than treated as "no due date".~~ Answered: reject; only absent or `null` mean no due date; see AC-001.7.

## Changelog

- 2026-11-05 created
- 2026-11-05 amended: answered the three open questions; clarified AC-001.5 (any Unicode whitespace-only title is rejected), AC-001.7 (`""` is rejected, only absent or `null` mean no due date) and AC-001.9 (length counts Unicode code points); no behaviour changed, no ids added or withdrawn
