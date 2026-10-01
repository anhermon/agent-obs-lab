#!/usr/bin/env bash
# Print the day-1 local runbook (compose + trace + agent).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cat <<MSG
agent-obs-lab — local run

1) Backend (Jaeger with OTLP):
     cd ${ROOT} && docker compose up -d

2) Proxy (mcp-trace + toy MCP server) in another terminal:
     ${ROOT}/scripts/run-trace.sh

3) Agent turn (≥2 tool calls):
     python3 ${ROOT}/lab/agent.py
     # failed-turn demo for eval blog outline:
     python3 ${ROOT}/lab/agent.py --fail-faq

4) Inspect spans:
     open http://localhost:16686
     # select service "agent-obs-lab" (or "mcp-trace" if --service-name omitted)

No Docker? Point OTEL_EXPORTER_OTLP_ENDPOINT at any OTLP collector, or run
mcp-trace without --otel-endpoint to skip export while you wire the agent.
MSG
