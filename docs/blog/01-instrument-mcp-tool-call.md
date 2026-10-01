# Draft outline: Instrument an MCP tool call

> Status: **outline / draft** — not a published blog post.

## Working title

*From "using tool…" to a real span: instrumenting MCP with mcp-trace*

## Audience

Engineers wiring agents to MCP servers who only see opaque "tool use" in the client UI.

## Outline

1. **Hook — the blank spot**  
   Agent says "using get_weather". No duration, no args keys, no error body. Debugging is guesswork.

2. **What MCP already gives you**  
   JSON-RPC `tools/call` with name + arguments + result/`isError`. Enough to build a span — if you sit on the wire.

3. **Drop in mcp-trace**  
   - Architecture: client → mcp-trace → MCP server; OTLP side-car.  
   - Lab repro: `docker compose up -d` → `./scripts/run-trace.sh` → `python lab/agent.py`.  
   - Screenshot placeholder: Jaeger row for `get_weather` + `calculate`.

4. **What the span should carry (pragmatic MVP)**  
   - `mcp.tool.name`, duration, ok/error  
   - argument *keys* (not secret values) — mcp-trace default  
   - W3C `traceparent` if the client propagates it  

5. **Common pitfalls**  
   - Tracing only the LLM call, not the tool proxy  
   - Capturing full args (PII / secrets)  
   - Mixing HTTP+SSE vs streamable vs stdio transports  

6. **Call to action**  
   Clone `agent-obs-lab`, produce one tool span in Jaeger, link the PR / screenshot in Dogfooding.

## Assets to gather later

- [ ] Jaeger screenshot (success + error)  
- [ ] 30s terminal recording (optional)  
- [ ] Link to mcp-trace release used  

## Non-goals for this post

Full custom OTel semantic conventions deep-dive; gateway mesh; monetization.
