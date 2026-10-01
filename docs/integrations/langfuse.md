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

1. Bake the Langfuse Collector config into the image (do **not** bind-mount under TCP `DOCKER_HOST`):

   ```bash
   export COLLECTOR_CONFIG=otel-collector.langfuse.yaml
   export LANGFUSE_AUTH_STRING=…   # see above
   export LANGFUSE_OTLP_ENDPOINT="${LANGFUSE_OTLP_ENDPOINT:-https://cloud.langfuse.com/api/public/otel}"
   docker compose -f docker-compose.fanout.yml build --build-arg COLLECTOR_CONFIG="$COLLECTOR_CONFIG" otel-collector
   # Pass secrets into the running Collector (add env: under otel-collector in compose, or):
   docker compose -f docker-compose.fanout.yml up -d
   ```

   Or rebuild via the compose `args` already wired to `${COLLECTOR_CONFIG:-otel-collector.yaml}`.

2. Ensure `LANGFUSE_AUTH_STRING` and `LANGFUSE_OTLP_ENDPOINT` are available to the Collector container environment (compose `environment:` / `.env`).
3. Keep mcp-trace → `localhost:4317` unchanged.

Do not commit real keys. Dogfood with a throwaway Langfuse project.

## Lab eval on the span first

`lab/eval.py` already attaches `eval.pass`, `eval.score`, `eval.rubric`, and per-assertion attributes/events to `agent.turn` (plus `artifacts/eval-result.json`). Prefer reading those in Jaeger / Phoenix before wiring Langfuse scores — still no SDK in the toy agent.

## Suggested next step

Map `eval.score` / `eval.pass` from the shared `trace_id` on `agent.turn` into a Langfuse score on a failed `lookup_faq` (`--fail-faq`) turn via Collector fan-out.
