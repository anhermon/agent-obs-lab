# Arize Phoenix (stub)

MVP status: **stub only** — env vars and wiring notes. No Phoenix instrumentation in the toy agent yet.

## What goes where

| Signal | Destination | Notes |
|--------|-------------|-------|
| MCP tool spans (OTLP) | Phoenix collector OTLP HTTP | mcp-trace already speaks OTLP; retarget or fan-out |
| Embeddings / retrieval evals | Phoenix datasets + evaluators | Out of MVP |
| Failed agent turns | Phoenix traces + annotations | Use `python lab/agent.py --fail-faq` as a fixture |

## Env vars

```bash
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT_NAME=agent-obs-lab
```

Local Phoenix (illustrative — not started by this repo's compose):

```bash
# example only; pin versions in your own fork when you enable this
pip install arize-phoenix
phoenix serve
```

Then either:

- set mcp-trace `--otel-http --otel-http-endpoint="$PHOENIX_COLLECTOR_ENDPOINT"`, or
- dual-export from an OTel Collector to Jaeger **and** Phoenix.

## Suggested next step (post-MVP)

Wire Collector fan-out, then add a Phoenix eval notebook under `docs/blog/` that loads a failed turn by `trace_id`.
