#!/usr/bin/env bash
# Orchestrate day-1 local backends, then remind how to run proxy + agent.
#
# Usage:
#   ./scripts/run-local.sh              # start Jaeger (compose or docker run)
#   ./scripts/run-local.sh --fanout     # Collector → Jaeger + Phoenix
#   ./scripts/run-local.sh --print-only # print the runbook without starting anything
#
# This script starts backends and waits for OTLP. It does NOT leave mcp-trace
# running in the foreground (that belongs in its own terminal via run-trace.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

FANOUT=0
PRINT_ONLY=0
for arg in "$@"; do
  case "${arg}" in
    --fanout) FANOUT=1 ;;
    --print-only) PRINT_ONLY=1 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown arg: ${arg} (try --help)" >&2
      exit 2
      ;;
  esac
done

print_runbook() {
  cat <<MSG
agent-obs-lab — local run

1) Backend already started by this script (or start yourself):
     docker compose up -d
     # fan-out: docker compose -f docker-compose.fanout.yml up -d --build
     # no compose: see README "docker run one-liner"

2) Proxy (mcp-trace + toy MCP server) in another terminal:
     ${ROOT}/scripts/run-trace.sh
     # Startup may WARN "not yet connected… spans will be lost silently"
     # until the first OTLP export succeeds — that is expected.

3) Agent turn (≥2 tool calls):
     python3 ${ROOT}/lab/agent.py
     python3 ${ROOT}/lab/agent.py --fail-faq

4) Inspect spans (allow ~2–5s for Jaeger flush / UI refresh after the agent exits):
     open http://localhost:16686   # service "agent-obs-lab"
     # fan-out also: http://localhost:6006 (Phoenix)
MSG
}

if [[ "${PRINT_ONLY}" -eq 1 ]]; then
  print_runbook
  exit 0
fi

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    cat >&2 <<'ERR'
docker CLI not found.

Install a Docker client (e.g. apt install docker.io) or use a remote daemon.
If the daemon listens on TCP instead of a unix socket:
  export DOCKER_HOST=tcp://127.0.0.1:2375

Debian/Ubuntu often lack the Compose v2 plugin package; install the plugin binary:
  mkdir -p ~/.docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
    -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose

Or skip Compose and use the README docker run one-liner for Jaeger.
ERR
    exit 1
  fi
  if [[ -z "${DOCKER_HOST:-}" ]] && [[ ! -S /var/run/docker.sock ]]; then
    if curl -fsS --max-time 1 http://127.0.0.1:2375/_ping >/dev/null 2>&1; then
      export DOCKER_HOST=tcp://127.0.0.1:2375
      echo "note: no unix docker.sock; using DOCKER_HOST=${DOCKER_HOST}" >&2
    else
      cat >&2 <<'ERR'
Cannot reach the Docker daemon (no /var/run/docker.sock).

If your daemon is TCP-only:
  export DOCKER_HOST=tcp://127.0.0.1:2375
ERR
      exit 1
    fi
  fi
}

have_compose() {
  docker compose version >/dev/null 2>&1
}

wait_otlp() {
  local deadline=$((SECONDS + 60))
  echo "waiting for OTLP gRPC on localhost:4317 …"
  while (( SECONDS < deadline )); do
    if (echo >/dev/tcp/127.0.0.1/4317) >/dev/null 2>&1; then
      echo "OTLP :4317 is accepting connections"
      return 0
    fi
    # bash /dev/tcp may be unavailable; fall back to python
    if python3 -c 'import socket; s=socket.create_connection(("127.0.0.1",4317),1); s.close()' 2>/dev/null; then
      echo "OTLP :4317 is accepting connections"
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for :4317 — check docker ps / logs" >&2
  return 1
}

start_jaeger_run() {
  local name="agent-obs-lab-jaeger"
  if docker ps -a --format '{{.Names}}' | grep -qx "${name}"; then
    docker start "${name}" >/dev/null
    echo "reused container ${name}"
  else
    docker run -d --name "${name}" \
      -e COLLECTOR_OTLP_ENABLED=true \
      -p 16686:16686 -p 4317:4317 -p 4318:4318 \
      jaegertracing/all-in-one:1.62.0 >/dev/null
    echo "started ${name} via docker run"
  fi
}

# Tear down the other compose file / docker-run Jaeger so :4317 is not held by
# a stale stack (fan-out port-wait must not succeed against default Jaeger).
stop_default_backends() {
  if have_compose; then
    docker compose -f docker-compose.yml down --remove-orphans >/dev/null 2>&1 || true
  fi
  docker rm -f agent-obs-lab-jaeger >/dev/null 2>&1 || true
}

stop_fanout_backends() {
  if have_compose; then
    docker compose -f docker-compose.fanout.yml down --remove-orphans >/dev/null 2>&1 || true
  fi
}

# Fail loudly if the Collector container is missing or not running. A bare
# :4317 listen can come from leftover Jaeger and would mask a dead Collector.
assert_fanout_collector() {
  local cid status
  cid="$(docker compose -f docker-compose.fanout.yml ps -q otel-collector 2>/dev/null || true)"
  if [[ -z "${cid}" ]]; then
    echo "fan-out: otel-collector container not found after up" >&2
    docker compose -f docker-compose.fanout.yml ps -a >&2 || true
    exit 1
  fi
  status="$(docker inspect -f '{{.State.Status}}' "${cid}" 2>/dev/null || echo missing)"
  if [[ "${status}" != "running" ]]; then
    echo "fan-out: otel-collector is ${status} (expected running)" >&2
    docker compose -f docker-compose.fanout.yml ps -a >&2 || true
    docker compose -f docker-compose.fanout.yml logs --tail=80 otel-collector >&2 || true
    exit 1
  fi
  echo "fan-out: otel-collector is running (${cid:0:12})"
}

ensure_docker

if [[ "${FANOUT}" -eq 1 ]]; then
  if ! have_compose; then
    echo "fan-out requires docker compose; install the Compose v2 plugin (see README)" >&2
    exit 1
  fi
  echo "stopping default Jaeger stack (if any) so :4317 is free for the Collector …"
  stop_default_backends
  echo "starting fan-out stack (Collector → Jaeger + Phoenix; baked config) …"
  # --build sends docker/ context to the daemon (works under TCP DOCKER_HOST)
  docker compose -f docker-compose.fanout.yml up -d --build
  assert_fanout_collector
  wait_otlp
  # Re-check after port-wait so a crash-loop / empty-config death cannot exit 0
  # against a stale listener on :4317.
  sleep 1
  assert_fanout_collector
else
  if have_compose; then
    echo "stopping fan-out stack (if any) so :4317 is free for Jaeger …"
    stop_fanout_backends
    echo "starting Jaeger via docker compose …"
    docker compose up -d
  else
    echo "docker compose unavailable — falling back to docker run one-liner …"
    start_jaeger_run
  fi
  wait_otlp
fi

echo
print_runbook
echo
echo "Tip: Jaeger may take ~2–5s after the agent exits before service agent-obs-lab appears."
