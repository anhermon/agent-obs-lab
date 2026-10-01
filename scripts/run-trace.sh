#!/usr/bin/env bash
# Wrap the toy MCP server with mcp-trace and export OTLP spans.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${MCP_TRACE_PORT:-8001}"
OTEL_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-localhost:4317}"
SERVICE_NAME="${MCP_TRACE_SERVICE_NAME:-agent-obs-lab}"

if ! command -v mcp-trace >/dev/null 2>&1; then
  echo "mcp-trace not found on PATH." >&2
  echo "Install: go install github.com/anhermon/mcp-trace/v2/cmd/mcp-trace@v2.0.3" >&2
  exit 1
fi

echo "mcp-trace :${PORT} → otel ${OTEL_ENDPOINT} (service=${SERVICE_NAME})"
echo "Client: python lab/agent.py --proxy http://localhost:${PORT}"
exec mcp-trace \
  --stdio \
  --port="${PORT}" \
  --otel-endpoint="${OTEL_ENDPOINT}" \
  --otel-insecure \
  --service-name="${SERVICE_NAME}" \
  -- \
  python3 "${ROOT}/lab/mcp_server.py"
