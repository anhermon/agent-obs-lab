#!/usr/bin/env bash
# Wrap the toy MCP server with mcp-trace and export OTLP spans.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${MCP_TRACE_PORT:-8001}"
OTEL_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-localhost:4317}"
SERVICE_NAME="${MCP_TRACE_SERVICE_NAME:-agent-obs-lab}"

# Prefer an explicit release binary or go-install path when present.
if [[ -n "${GOPATH:-}" && -x "${GOPATH}/bin/mcp-trace" ]]; then
  PATH="${GOPATH}/bin:${PATH}"
elif command -v go >/dev/null 2>&1; then
  PATH="$(go env GOPATH)/bin:${PATH}"
fi
export PATH

if ! command -v mcp-trace >/dev/null 2>&1; then
  cat >&2 <<'ERR'
mcp-trace not found on PATH.

Install (pick one):

  # Go install (then put GOPATH/bin on PATH):
  go install github.com/anhermon/mcp-trace/v2/cmd/mcp-trace@v2.0.3
  export PATH="$(go env GOPATH)/bin:$PATH"

  # Or download a release binary (no Go required):
  # https://github.com/anhermon/mcp-trace/releases
  # install the binary somewhere on PATH (e.g. ~/.local/bin)

Then re-run: ./scripts/run-trace.sh
ERR
  exit 1
fi

echo "mcp-trace :${PORT} → otel ${OTEL_ENDPOINT} (service=${SERVICE_NAME})"
echo "Client: python3 lab/agent.py --proxy http://localhost:${PORT}"
echo "Note: a startup WARN about OTLP 'not yet connected' is normal until the first export."
exec mcp-trace \
  --stdio \
  --port="${PORT}" \
  --otel-endpoint="${OTEL_ENDPOINT}" \
  --otel-insecure \
  --service-name="${SERVICE_NAME}" \
  -- \
  python3 "${ROOT}/lab/mcp_server.py"
