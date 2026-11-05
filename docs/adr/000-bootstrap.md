# ADR-000: Bootstrap

## Status

Accepted on bootstrap.

## Context

`task-api` was created from the `service-python` Copier template at `ika100/sdlc-foundry`. The template encodes a set of conventions every service in the fleet shares:

- Python 3.12 via devbox
- FastAPI for HTTP
- pytest with ≥80% coverage gate
- ruff + mypy for quality
- pip-audit + detect-secrets + bandit + trivy for security
- Multi-stage Docker build → `ghcr.io/ika100-demo/task-api`
- No Kubernetes manifests here: the system's gitops-app repo owns them (platform ADR-017); this repo ships a container image
- GitHub topic `deployable-service` for ArgoCD auto-discovery
- Claude Code agents from the `sdlc-foundry` marketplace (`svc` + `shared`)
- structlog + Prometheus + OTel for observability

## Decision

We adopt the platform conventions verbatim. Any deviation must be justified in a new ADR.

The platform marketplace is pinned to `main` in `.claude/settings.json` — bump that ref to pull updated agents/commands. Skeleton updates (CI workflow, devbox recipes) come via `copier update`.

## Consequences

**Positive:** zero per-service plumbing decisions; consistent quality bar; agents work identically across the fleet; new contributors learn one shape and apply it everywhere.

**Negative:** drift requires deliberate work — if `task-api` needs a tool that's not in the template, the right answer is to upstream it to the template, not work around it locally.
