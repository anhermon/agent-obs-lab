# Langfuse (stub)

MVP status: **stub only** — env vars and wiring notes. No live Langfuse client in the toy agent yet.

## What goes where

| Signal | Destination | Notes |
|--------|-------------|-------|
| MCP `tools/call` spans | Already exported by [mcp-trace](https://github.com/anhermon/mcp-trace) via OTLP | Point a collector → Langfuse OTLP intake, or dual-export |
| LLM generations / prompts | Langfuse traces / observations | Add when the agent gains a real model call |
| Eval scores | Langfuse scores on the trace / observation | Use failed-turn demos (`--fail-faq`) as fixtures |

## Env vars

Copy from `.env.example`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com   # or self-hosted URL
```

## Suggested next step (post-MVP)

1. Keep mcp-trace → Jaeger for tool spans (day-1 path).
2. Add an OTel Collector exporter (or Langfuse native OTLP) so the same spans land in Langfuse.
3. When the agent calls an LLM, wrap that call with the Langfuse Python/JS SDK and link `trace_id` to the mcp-trace spans via W3C `traceparent`.

Do not commit real keys. Dogfood with a throwaway Langfuse project.
