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
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

FANOUT=0
PRINT_ONLY=0
# Set when the Docker daemon answers on TCP but no docker CLI is on PATH.
AGENT_OBS_DOCKER_API="${AGENT_OBS_DOCKER_API:-0}"

print_runbook() {
  cat <<MSG
agent-obs-lab — local run

No Docker needed for evals:
     python3 ${ROOT}/lab/compare.py
     pytest -q

Live traces (optional) — backend already started by this script (or start yourself):
     docker compose up -d
     # fan-out: docker compose -f docker-compose.fanout.yml up -d --build
     # no compose: see README "docker run one-liner"

Proxy (mcp-trace + toy MCP server) in another terminal:
     ${ROOT}/scripts/run-trace.sh
     # Startup may WARN "not yet connected… spans will be lost silently"
     # until the first OTLP export succeeds — that is expected.

Agent turn (≥2 tool calls):
     python3 ${ROOT}/lab/agent.py
     python3 ${ROOT}/lab/agent.py --fail-faq
     # --fail-faq exits 1 on purpose (rubric failure), not a crash.

Inspect spans (allow ~2–5s for Jaeger flush / UI refresh after the agent exits):
     open http://localhost:16686   # service "agent-obs-lab"
     # fan-out also: http://localhost:6006 (Phoenix)
MSG
}

docker_tcp_reachable() {
  case "${AGENT_OBS_DOCKER_TCP_REACHABLE:-auto}" in
    1|true|yes) return 0 ;;
    0|false|no) return 1 ;;
  esac
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 1 http://127.0.0.1:2375/_ping >/dev/null 2>&1; then
      return 0
    fi
  fi
  python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:2375/_ping", timeout=1).read()' >/dev/null 2>&1
}

print_missing_docker_hint() {
  cat >&2 <<'ERR'
docker CLI not found.

A day-1 lab can still use a Docker daemon that answers TCP :2375 (no unix socket).
Install a Docker client and point it at that daemon:

  export DOCKER_HOST=tcp://127.0.0.1:2375

  # client, e.g.:
  #   apt install docker.io
  # or a static binary on PATH (e.g. ~/.local/bin/docker)

Debian/Ubuntu often lack the Compose v2 plugin package; install the plugin binary:
  mkdir -p ~/.docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
    -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose

Or skip Compose and use the README docker run one-liner for Jaeger.
Default Jaeger (no --fanout) is started via the daemon HTTP API when the CLI
is missing but http://127.0.0.1:2375/_ping succeeds.
ERR
}

# stdin: name<TAB>status<TAB>ports  (status "Up…"/"running")
# stdout: one running container with host port 4317 published, else empty.
# Prefer our Jaeger names. An exposed "4317/tcp" without "-> " is not enough.
pick_reusable_publisher() {
  python3 -c '
import sys

def host_publishes(ports: str, port: int) -> bool:
    """True when ports text maps host port, not merely exposes it."""
    for token in ports.replace(",", " ").split():
        if "->" not in token:
            continue
        host = token.split("->", 1)[0]
        if host.startswith("["):
            host = host.split("]", 1)[-1].lstrip(":")
        elif ":" in host:
            host = host.rsplit(":", 1)[-1]
        if "-" in host:
            left, right = host.split("-", 1)
            if left.isdigit() and right.isdigit() and int(left) <= port <= int(right):
                return True
        elif host.isdigit() and int(host) == port:
            return True
    return False


rows = []
for line in sys.stdin:
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 3:
        continue
    name, status, ports = parts[0].lstrip("/"), parts[1], parts[2]
    running = status.lower().startswith("up") or status.lower() == "running"
    # Host bind only. "4317-4318/tcp" is an exposed container port on a
    # Jaeger that maps :16686 and must not count as an OTLP publisher.
    if running and host_publishes(ports, 4317):
        rows.append(name)

def rank(name: str) -> tuple:
    preferred = (
        name == "agent-obs-lab-jaeger"
        or name.endswith("-jaeger-1")
        or ("jaeger" in name and "agent-obs-lab" in name)
    )
    return (0 if preferred else 1, name)

if not rows:
    sys.exit(0)
rows.sort(key=rank)
print(rows[0])
'
}

list_containers_tsv() {
  if [[ "${AGENT_OBS_DOCKER_API}" == 1 ]]; then
    DOCKER_HOST="${DOCKER_HOST:-tcp://127.0.0.1:2375}" python3 - <<'PY'
import json, os, urllib.request

host = os.environ.get("DOCKER_HOST", "tcp://127.0.0.1:2375")
if host.startswith("tcp://"):
    base = "http://" + host[len("tcp://"):]
else:
    raise SystemExit("DOCKER_HOST must be tcp:// for the API fallback")
base = base.rstrip("/")
with urllib.request.urlopen(base + "/containers/json?all=1", timeout=5) as resp:
    containers = json.loads(resp.read().decode())
for c in containers:
    names = c.get("Names") or ["/unknown"]
    name = names[0].lstrip("/")
    state = c.get("State") or ""
    ports = []
    for p in c.get("Ports") or []:
        pub = p.get("PublicPort")
        priv = p.get("PrivatePort")
        if pub:
            ports.append(f"{pub}->{priv}/{p.get('Type','tcp')}")
        elif priv:
            ports.append(str(priv))
    print(f"{name}\t{state}\t{' '.join(ports)}")
PY
  else
    docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
  fi
}

reusable_otlp_container() {
  list_containers_tsv | pick_reusable_publisher
}

otlp_accepting() {
  if (echo >/dev/tcp/127.0.0.1/4317) >/dev/null 2>&1; then
    return 0
  fi
  python3 -c 'import socket; s=socket.create_connection(("127.0.0.1",4317),1); s.close()' 2>/dev/null
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    local cand
    if [[ "${AGENT_OBS_SKIP_DOCKER_DISCOVERY:-0}" != 1 ]]; then
      for cand in "${HOME}/.local/bin/docker" /usr/local/bin/docker /usr/bin/docker; do
        if [[ -x "${cand}" ]]; then
          export PATH="$(dirname "${cand}"):${PATH}"
          echo "note: using docker client at ${cand}" >&2
          break
        fi
      done
    fi
  fi

  if ! command -v docker >/dev/null 2>&1; then
    if docker_tcp_reachable; then
      export DOCKER_HOST="${DOCKER_HOST:-tcp://127.0.0.1:2375}"
      AGENT_OBS_DOCKER_API=1
      echo "note: no docker CLI; daemon answered ${DOCKER_HOST} (_ping). Using the Docker HTTP API for Jaeger." >&2
      return 0
    fi
    print_missing_docker_hint
    exit 1
  fi

  if [[ -z "${DOCKER_HOST:-}" ]] && [[ ! -S /var/run/docker.sock ]]; then
    if docker_tcp_reachable; then
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
  [[ "${AGENT_OBS_DOCKER_API}" == 1 ]] && return 1
  docker compose version >/dev/null 2>&1
}

wait_otlp() {
  local deadline=$((SECONDS + 60))
  echo "waiting for OTLP gRPC on localhost:4317 …"
  while (( SECONDS < deadline )); do
    if otlp_accepting; then
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
  if docker ps --format '{{.Names}}' | grep -qx "${name}"; then
    echo "reused container ${name}"
    return 0
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "${name}"; then
    if docker start "${name}" >/dev/null; then
      echo "reused container ${name}"
      return 0
    fi
    echo "existing ${name} did not start (port may already be held)" >&2
    return 1
  fi
  docker run -d --name "${name}" \
    -e COLLECTOR_OTLP_ENABLED=true \
    -p 16686:16686 -p 4317:4317 -p 4318:4318 \
    jaegertracing/all-in-one:1.62.0 >/dev/null
  echo "started ${name} via docker run"
}

# Start Jaeger through the engine API when the CLI is absent but TCP :2375 is up.
api_start_jaeger() {
  DOCKER_HOST="${DOCKER_HOST:-tcp://127.0.0.1:2375}" python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request

host = os.environ.get("DOCKER_HOST", "tcp://127.0.0.1:2375")
if not host.startswith("tcp://"):
    sys.exit("DOCKER_HOST must be tcp:// for the API fallback")
base = "http://" + host[len("tcp://"):].rstrip("/")
image = "jaegertracing/all-in-one:1.62.0"
name = "agent-obs-lab-jaeger"

def req(method, path, body=None, timeout=120):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()

def containers():
    status, raw = req("GET", "/containers/json?all=1", timeout=10)
    if status != 200:
        raise SystemExit(f"docker API list failed: HTTP {status} {raw[:200]!r}")
    return json.loads(raw.decode())

def publishes_4317(c):
    for p in c.get("Ports") or []:
        if p.get("PublicPort") == 4317:
            return True
    return False

found = containers()
for c in found:
    if (c.get("State") == "running") and publishes_4317(c):
        cname = (c.get("Names") or ["container"])[0].lstrip("/")
        print(f"reusing running container {cname} (already publishing :4317)")
        sys.exit(0)

existing = None
for c in found:
    names = [n.lstrip("/") for n in (c.get("Names") or [])]
    if name in names:
        existing = c
        break

def start_id(cid):
    status, raw = req("POST", f"/containers/{cid}/start", timeout=30)
    if status in (204, 304):
        print(f"reused container {name}")
        return True
    sys.stderr.write(f"docker API start {cid[:12]} failed: HTTP {status} {raw[:300]!r}\n")
    return False

if existing is not None:
    if start_id(existing["Id"]):
        sys.exit(0)
    for c in containers():
        if c.get("State") == "running" and publishes_4317(c):
            cname = (c.get("Names") or ["container"])[0].lstrip("/")
            print(f"reusing running container {cname} (already publishing :4317)")
            sys.exit(0)
    sys.exit(1)

status, raw = req(
    "POST",
    "/images/create?fromImage=jaegertracing/all-in-one&tag=1.62.0",
    timeout=180,
)
if status not in (200, 201):
    sys.stderr.write(f"docker API image pull failed: HTTP {status} {raw[:300]!r}\n")
    sys.exit(1)

body = {
    "Image": image,
    "Env": ["COLLECTOR_OTLP_ENABLED=true"],
    "ExposedPorts": {"16686/tcp": {}, "4317/tcp": {}, "4318/tcp": {}},
    "HostConfig": {
        "PortBindings": {
            "16686/tcp": [{"HostPort": "16686"}],
            "4317/tcp": [{"HostPort": "4317"}],
            "4318/tcp": [{"HostPort": "4318"}],
        }
    },
}
status, raw = req("POST", f"/containers/create?name={name}", body, timeout=30)
if status not in (200, 201):
    sys.stderr.write(f"docker API create failed: HTTP {status} {raw[:300]!r}\n")
    for c in containers():
        if c.get("State") == "running" and publishes_4317(c):
            cname = (c.get("Names") or ["container"])[0].lstrip("/")
            print(f"reusing running container {cname} (already publishing :4317)")
            sys.exit(0)
    sys.exit(1)
cid = json.loads(raw.decode())["Id"]
if not start_id(cid):
    sys.exit(1)
print(f"started {name} via Docker HTTP API")
PY
}

# Default-path Jaeger containers. Reuse (pick_reusable_publisher) accepts the
# Compose name agent-obs-lab-jaeger-1 and the docker-run name agent-obs-lab-jaeger.
# `docker compose down` only removes the current project, so fan-out must also
# remove these by name or :16686 stays allocated.
names_of_default_jaegers() {
  python3 -c '
import sys

def is_default_jaeger(name: str) -> bool:
    name = name.lstrip("/")
    if name in ("agent-obs-lab-jaeger", "agent-obs-lab-jaeger-1"):
        return True
    # Sibling checkouts (agent-obs-lab-dogfood-jaeger-1, …) publish the same host ports.
    if name.endswith("-jaeger-1") and "agent-obs-lab" in name:
        return True
    return False

seen = set()
for line in sys.stdin:
    name = line.split("\t", 1)[0].strip().lstrip("/")
    if not name or name in seen or not is_default_jaeger(name):
        continue
    seen.add(name)
    print(name)
'
}

# Fan-out binds :16686 (Jaeger), :6006 (Phoenix), :4317 and :4318 (Collector).
# Compose down only removes this project. Sibling checkouts
# (agent-obs-lab-dogfood-phoenix-1, …) keep those host ports unless named here.
names_blocking_fanout() {
  python3 -c '
import sys

def is_default_jaeger(name: str) -> bool:
    if name in ("agent-obs-lab-jaeger", "agent-obs-lab-jaeger-1"):
        return True
    return name.endswith("-jaeger-1") and "agent-obs-lab" in name

def blocks_fanout(name: str) -> bool:
    if is_default_jaeger(name):
        return True
    if "agent-obs-lab" not in name:
        return False
    return name.endswith("-phoenix-1") or name.endswith("-otel-collector-1")

seen = set()
for line in sys.stdin:
    name = line.split("\t", 1)[0].strip().lstrip("/")
    if not name or name in seen or not blocks_fanout(name):
        continue
    seen.add(name)
    print(name)
'
}

api_force_remove_container() {
  local name="$1"
  DOCKER_HOST="${DOCKER_HOST:-tcp://127.0.0.1:2375}" python3 - "$name" <<'PY'
import json, os, sys, urllib.request
name = sys.argv[1]
host = os.environ.get("DOCKER_HOST", "tcp://127.0.0.1:2375")
if not host.startswith("tcp://"):
    sys.exit(0)
base = "http://" + host[len("tcp://"):].rstrip("/")

def req(method, path):
    r = urllib.request.Request(base + path, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, resp.read()
    except Exception:
        return 0, b""

status, raw = req("GET", "/containers/json?all=1")
if status != 200:
    sys.exit(0)
for c in json.loads(raw.decode()):
    names = [n.lstrip("/") for n in (c.get("Names") or [])]
    if name in names:
        cid = c["Id"]
        req("POST", f"/containers/{cid}/stop")
        req("DELETE", f"/containers/{cid}?force=1")
PY
}

remove_container_by_name() {
  local name="$1"
  if [[ "${AGENT_OBS_DOCKER_API}" == 1 ]]; then
    api_force_remove_container "${name}" || true
  else
    docker rm -f "${name}" >/dev/null 2>&1 || true
  fi
}

stop_default_backends() {
  local names name
  if have_compose; then
    docker compose -f docker-compose.yml down --remove-orphans >/dev/null 2>&1 || true
  fi
  # Listing can fail (no CLI). Still remove the two names reuse accepts.
  names="$(
    list_containers_tsv 2>/dev/null | names_blocking_fanout || true
    printf '%s\n' agent-obs-lab-jaeger agent-obs-lab-jaeger-1
  )"
  names="$(printf '%s\n' "${names}" | awk 'NF && !seen[$0]++')"
  while IFS= read -r name; do
    [[ -z "${name}" ]] && continue
    remove_container_by_name "${name}"
  done <<< "${names}"
}

stop_fanout_backends() {
  if have_compose; then
    docker compose -f docker-compose.fanout.yml down --remove-orphans >/dev/null 2>&1 || true
  fi
}

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

start_default_backend() {
  local holder=""
  holder="$(reusable_otlp_container || true)"
  if [[ -n "${holder}" ]]; then
    echo "reusing running container ${holder} (already publishing :4317)"
    return 0
  fi
  if otlp_accepting; then
    echo "OTLP :4317 is already accepting connections; not starting another Jaeger"
    return 0
  fi
  if [[ "${AGENT_OBS_DOCKER_API}" == 1 ]]; then
    echo "starting Jaeger via Docker HTTP API (${DOCKER_HOST}) …"
    api_start_jaeger
    return 0
  fi
  if have_compose; then
    echo "stopping fan-out stack (if any) so :4317 is free for Jaeger …"
    stop_fanout_backends
    echo "starting Jaeger via docker compose …"
    if ! docker compose up -d; then
      holder="$(reusable_otlp_container || true)"
      if [[ -n "${holder}" ]] || otlp_accepting; then
        echo "compose up failed but :4317 is already served by ${holder:-an existing listener}; reusing it"
        return 0
      fi
      echo "no container is publishing host :4317. A Jaeger that only maps :16686 is not reused as the trace backend." >&2
      return 1
    fi
  else
    echo "docker compose unavailable — falling back to docker run one-liner …"
    if ! start_jaeger_run; then
      holder="$(reusable_otlp_container || true)"
      if [[ -n "${holder}" ]] || otlp_accepting; then
        echo "reusing running container ${holder:-listener} (already publishing :4317)"
        return 0
      fi
      echo "no container is publishing host :4317. A Jaeger that only maps :16686 is not reused as the trace backend." >&2
      return 1
    fi
  fi
}

main() {
  for arg in "$@"; do
    case "${arg}" in
      --fanout) FANOUT=1 ;;
      --print-only) PRINT_ONLY=1 ;;
      -h|--help)
        sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
      *)
        echo "unknown arg: ${arg} (try --help)" >&2
        exit 2
        ;;
    esac
  done

  if [[ "${PRINT_ONLY}" -eq 1 ]]; then
    print_runbook
    exit 0
  fi

  ensure_docker

  if [[ "${FANOUT}" -eq 1 ]]; then
    if ! have_compose; then
      echo "fan-out requires docker compose; install a Docker client and the Compose v2 plugin." >&2
      echo "export DOCKER_HOST=tcp://127.0.0.1:2375" >&2
      if ! command -v docker >/dev/null 2>&1; then
        print_missing_docker_hint
      fi
      exit 1
    fi
    echo "stopping Jaeger plus any sibling Phoenix or collector holding :16686, :6006, :4317, or :4318 …"
    stop_default_backends
    echo "starting fan-out stack (Collector → Jaeger + Phoenix; baked config) …"
    docker compose -f docker-compose.fanout.yml up -d --build
    assert_fanout_collector
    wait_otlp
    sleep 1
    assert_fanout_collector
  else
    start_default_backend
    wait_otlp
  fi

  echo
  print_runbook
  echo
  echo "Tip: Jaeger may take ~2–5s after the agent exits before service agent-obs-lab appears."
  echo "Tip: python3 lab/agent.py --fail-faq exits 1 on purpose (failed rubric)."
  echo "Tip: with no collector, the agent skips traces (eval JSON is still written); that is not a hard failure."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
