# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**task-api** — Task API for the taskboard system

Owned by @ika100-demo. Python module: `task_api`. Container image: `ghcr.io/ika100-demo/task-api`.

## Development Environment

This project uses [devbox](https://www.jetify.com/devbox) to manage the dev environment.

```bash
devbox shell       # enter the dev environment
devbox run test    # full pytest run with coverage
devbox run quality # ruff + mypy gate
```

Canonical `devbox run` scripts (configured in `devbox.json`):

| Script | Purpose |
|---|---|
| `test` | Full pytest run with coverage (`--cov=task_api --cov-report=term-missing`) |
| `test-fast` | Quick pytest run without coverage |
| `lint` | `ruff check` + `ruff format --check` |
| `lint-fix` | `ruff check --fix` + `ruff format` |
| `typecheck` | `mypy .` |
| `quality` | `lint` then `typecheck` — the gate CI runs |
| `audit` | `pip-audit --strict` |
| `secrets-scan` | `detect-secrets-hook` against `.secrets.baseline.json` |
| `bandit` | `bandit -r src/ -q` |
| `security` | `audit` + `secrets-scan` + `bandit` |
| `secrets-baseline` | refresh `.secrets.baseline.json` with fixed flags (never run `detect-secrets scan` by hand) |
| `ci` | `quality` + `test` + `security`: the gates CI runs, then `ci-extra` when your repo defines it; run it before every push |
| `image-build` | Build local container image `task-api:scan` |
| `image-scan` | `trivy image --severity CRITICAL,HIGH` against `task-api:scan` |

**Rule for every agent (human, CI, and AI): never call `ruff`, `mypy`, `pytest`, `pip-audit`, `detect-secrets`, `trivy`, `bandit`, `pip`, or `uv add` directly. Always go through `devbox run <script>`.**

## Claude Code agents

Agents and slash commands come from the [`ika100/sdlc-foundry`](https://github.com/ika100/sdlc-foundry) marketplace. The plugins are enabled in `.claude/settings.json`:

- `svc@sdlc-foundry` — pipeline agents (product-manager, architect, coder, tester, migrations, observability, release, deployment)
- `component@sdlc-foundry` — the commands: `/component:spec`, `plan`, `build`, `ship`, `fix`, `check`, `release`
- `instance@sdlc-foundry`, `api@sdlc-foundry`, `issue@sdlc-foundry`, `platform@sdlc-foundry` — `/instance:promote`, `/api:list`, `/issue:report`, `/platform:update`
- `shared@sdlc-foundry` — quality and security agents, the `cplat` launcher

Read the platform's `docs/AGENTS.md` for the full orchestration model.

### Common workflows

| Task | Command |
|---|---|
| Write a feature spec (first step) | `/component:spec <description>` |
| Plan the approved spec | `/component:plan <NNN>` |
| Build it: tests first, verified | `/component:build <NNN>` |
| All of it unattended: build, PR, merge on green CI, dev | `/component:ship <NNN>` (headless: `cplat headless "/component:ship <NNN>"`) |
| Where specs stand | `/component:spec --all` |
| Small change | `/component:fix <description>` |
| Read-only quality + security audit | `/component:check` |
| Release | `/component:release` |

### Spec first

A feature starts with a spec, not code ([ADR-026](https://github.com/ika100/sdlc-foundry/blob/main/docs/adr/026-feature-specs.md)): `/component:spec <description>` writes `docs/specs/<NNN>-<slug>/spec.md` with acceptance criteria `AC-<NNN>.<n>` and asks you its open questions; approve it (`/component:spec approve <NNN>`), plan it (`/component:plan <NNN>`), then build it (`/component:build <NNN>`): acceptance tests are written from the criteria first and fail, the code makes them pass, a reviewer checks the result against the spec, and the PR lists every criterion. Tests that name a criterion are the spec in code: never weaken them; change the spec instead (`/component:spec --amend <NNN> <change>`). `/component:spec --all` shows where each spec stands; `devbox run spec-check` validates every spec and traces built ones to their tests (also the warn-only `specs` CI workflow). Small changes and bug fixes (`/component:fix`) need no spec, but stop when they would change a criterion.

## Feature Branch Workflow

Branch prefixes: `feature/`, `fix/`, `chore/`, `docs/`, `refactor/`, `release/`. Slugs: lowercase, hyphens, ≤40 chars.

Main is protected. All changes via PR. Required CI checks: `quality`, `test`, `security`, `pr-title`, `docker`.

PR title format: `<type>(<optional-scope>): <description ≤72 chars>`. Valid types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`, `build`, `revert`.

## Where your additions go

Updates (`/platform:update`) overwrite the skeleton files below. Put your own work next to them, where an update keeps it:

| Updates overwrite | Your additions go in |
|---|---|
| the template's recipes in `devbox.json` (including `ci`) | gates: the `ci-extra` recipe (`devbox run ci` and the `ci-extra` CI check run it); other tools: recipes of your own in `devbox.json` (kept) |
| `.github/workflows/ci.yml` | a workflow file of your own in `.github/workflows/` |
| `.claude/settings.json` | your own permission entries (allow, ask, deny) in it; they are kept |
| `CLAUDE.md` | `.claude/project-notes.md` |
| other skeleton files (Dockerfile, lint config ...) | nowhere: propose the change to the platform (`/issue:report`) |

## Conventions

- **Config:** read exclusively from environment variables
- **HTTP services:** expose `/health` and `/ready` endpoints
- **Logging:** structured JSON via structlog
- **Tests:** pytest, in `tests/`, fixtures in `conftest.py`
- **Docs:** feature specs in `docs/specs/` (index in `docs/backlog.md`), ADRs in `docs/adr/`

## Docker image pipeline

Whenever a `Dockerfile` exists, the CI workflow includes a `docker (build + push)` job that:

| Trigger | Tags pushed |
|---|---|
| PR | Build only — no push |
| Merge to `main` | `latest`, `sha-<40>`, `sha-<short>` |
| Version tag `v1.2.3` | `1.2.3`, `1.2`, `1`, `latest`, `sha-<40>`, `sha-<short>` |

Registry: `ghcr.io/ika100-demo/task-api`. Authentication via `GITHUB_TOKEN`.

## Deployment

This repo ships **only a container image**. Kubernetes manifests, environment wiring (e.g. `API_URL`), replicas, resources and exposure belong to the system's `gitops-app` repo (platform ADR-017): register the component with `/component:add task-api` in the system's repo (needs the GitHub topic `deployable-service`, set by `/component:new`), then `/instance:promote task-api --to <env>`. Change how the service runs by editing its entry under `components:` in that repo's `system.yaml`; change the port, probe paths or user in the Dockerfile/app and update the entry to match.

## Project notes

Project-specific guidance for Claude Code goes in `.claude/project-notes.md`, which is loaded below and never changed by updates.

@.claude/project-notes.md
