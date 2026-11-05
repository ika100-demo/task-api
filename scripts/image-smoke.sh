#!/usr/bin/env bash
# Run task-api:scan like Kubernetes would (read-only rootfs, tmpfs /tmp, numeric user) and probe it.
set -euo pipefail
name=task-api-smoke
port="${SMOKE_PORT:-18080}"
docker rm -f "$name" >/dev/null 2>&1 || true
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$name" --read-only --tmpfs /tmp --user 10001:10001 \
  -e PORT=8080 -p "$port:8080" task-api:scan >/dev/null
for _ in $(seq 1 30); do curl -fs "localhost:$port/health" >/dev/null 2>&1 && break; sleep 1; done
echo "health: $(curl -fs localhost:$port/health)"
echo "ready: $(curl -fs localhost:$port/ready)"
echo "uid: $(docker exec "$name" id -u)"
echo "processes: $(docker exec "$name" sh -c 'ls /proc | grep -c "^[0-9]"') (uvicorn cmd: $(docker inspect -f '{{.Config.Cmd}}' "$name"))"
echo "POST: $(curl -s -w ' [%{http_code}]' -X POST localhost:$port/tasks -H 'content-type: application/json' -d '{"title":"smoke"}')"
echo "GET: $(curl -s -w ' [%{http_code}]' localhost:$port/tasks)"
docker logs "$name" 2>&1 | tail -5
