# Langfuse

MVP status: **Collector exporter documented** for scores. No Langfuse SDK in the toy agent — do not dual-SDK alongside Phoenix.

## What goes where

| Signal | Destination | Notes |
|--------|-------------|-------|
| MCP `tools/call` spans | Already exported by [mcp-trace](https://github.com/anhermon/mcp-trace) via OTLP | Fan out through the Collector |
| Turn parent (`agent.turn`) | Same OTLP stream | From `lab/agent.py` |
| LLM generations / prompts | Langfuse traces / observations | Add when the agent gains a real model call |
| Eval scores | Langfuse scores on the trace / observation | Use `--fail-faq` turns as fixtures |

## Prefer Phoenix first, then Langfuse

Local dogfood: use [Phoenix](phoenix.md) via `docker-compose.fanout.yml` (zero-key).  
When you need **scores** / cloud demos for blog 02, enable the Langfuse OTLP exporter on the Collector (below) — still no SDK in the agent.

## Env vars

Copy from `.env.example`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com   # or self-hosted URL
LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
```

Build the Basic auth string the Collector expects:

```bash
export LANGFUSE_AUTH_STRING="$(printf '%s' "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64 -w0 2>/dev/null || printf '%s' "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64)"
```

## Enable Collector → Langfuse

1. Start the fan-out stack but mount `docker/otel-collector.langfuse.yaml` as the Collector config (see comments in that file).
2. Pass `LANGFUSE_AUTH_STRING` and `LANGFUSE_OTLP_ENDPOINT` into the Collector service environment.
3. Keep mcp-trace → `localhost:4317` unchanged.

Do not commit real keys. Dogfood with a throwaway Langfuse project.

## Suggested next step

Score a failed `lookup_faq` turn in Langfuse using the shared `trace_id` from `agent.turn` + child tool spans.
