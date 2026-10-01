# Arize Phoenix

MVP status: **Collector fan-out ready** (local, zero-key). No Phoenix SDK in the toy agent — mcp-trace remains the sole span producer.

## What goes where

| Signal | Destination | Notes |
|--------|-------------|-------|
| MCP tool spans (OTLP) | Phoenix via OTel Collector | `docker compose -f docker-compose.fanout.yml up -d` |
| Turn parent (`agent.turn`) | Same pipeline (OTLP/HTTP `:4318`) | Emitted by `lab/agent.py` (stdlib JSON, not Phoenix SDK) |
| Embeddings / retrieval evals | Phoenix datasets + evaluators | Out of MVP |
| Failed agent turns | Phoenix traces + annotations | Use `python3 lab/agent.py --fail-faq` |

## Quick start (fan-out)

```bash
./scripts/run-local.sh --fanout
# or: docker compose -f docker-compose.fanout.yml up -d
./scripts/run-trace.sh          # still targets localhost:4317 (Collector)
python3 lab/agent.py --fail-faq
# wait ~2–5s, then:
open http://localhost:6006      # Phoenix
open http://localhost:16686     # Jaeger (same spans)
```

Env vars (informational — Collector talks to Phoenix on the compose network):

```bash
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT_NAME=agent-obs-lab
```

## Why Collector instead of dual-SDK

Pointing mcp-trace at Phoenix **or** Jaeger works, but fan-out through the Collector keeps a single producer and lets you add Langfuse scores later without instrumenting `lab/agent.py` twice.

## Suggested next step

Add a Phoenix eval notebook under `docs/blog/` that loads a failed turn by `trace_id` (still outline-only until fixtures exist).
