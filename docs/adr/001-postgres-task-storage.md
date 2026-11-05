# ADR-001: Postgres task storage with psycopg 3, a connection pool and a self-created schema

## Status

Accepted (spec 002).

## Context

Spec 002 moves tasks from process memory into the Postgres database the system's gitops repo provides
(`DATABASE_URL`). The service must start and stay live while the database is down, report not ready instead, recover
without a restart, and run as several instances. Spec 002 rules out a migration tool for now (non-goal) and fixes the
driver choice (psycopg 3 with psycopg_pool).

## Decision

- Access Postgres with **psycopg 3** (sync API) and **one `psycopg_pool.ConnectionPool` per process**, opened without
  waiting so a missing database never blocks startup. Every connection carries `connect_timeout=2` and
  `statement_timeout=2000`; checkout waits at most 2 s; broken connections are discarded on checkout
  (`check_connection`); `reconnect_timeout=10` keeps the reconnect backoff short.
- Database failures are translated at the store boundary into one domain exception (`TaskStoreUnavailable`), mapped
  to `503` by an app-level handler. No psycopg type leaks above the store.
- `/ready` runs `SELECT 1` on every call; `/health` never touches the database.
- The **service creates its own schema** with idempotent DDL (`CREATE TABLE IF NOT EXISTS`) on the first successful
  checkout, serialised across instances by a transaction-scoped advisory lock. No ORM, no migration tool.
- Rows carry an **identity column `seq`** that defines creation order; nothing orders by time.
- Integration tests run against a **real Postgres via testcontainers-python**; no SQLite or mocks for the store.

## Consequences

**Positive:** stateless, horizontally scalable instances; predictable worst-case latencies while the database is
down; no extra tooling or init job; tests exercise the real SQL.

**Negative:** schema evolution beyond "create when missing" needs a later decision (a migration tool or versioned DDL)
once a column changes. Tests need Docker. The pool's background reconnect behaviour is a library detail the recovery
tests must keep covering.
