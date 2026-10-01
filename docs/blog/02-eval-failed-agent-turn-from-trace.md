# Draft outline: Eval a failed agent turn from a trace

> Status: **outline / draft** — not a published blog post.

## Working title

*The span said it failed — now score the turn*

## Audience

Builders who have traces but no eval loop yet.

## Outline

1. **Hook**  
   A trace with a red `lookup_faq` span. Users felt a bad answer. Can we grade it offline?

2. **Produce a failed turn in the lab**  
   ```bash
   docker compose up -d
   ./scripts/run-trace.sh
   python lab/agent.py --fail-faq
   ```  
   Find the trace in Jaeger: parent turn (if present) + child tool spans; `isError` / error text on `lookup_faq`.

3. **Minimal eval rubric (stub)**  
   - Did every required tool succeed?  
   - Did the agent recover (retry / alternate tool) or stop?  
   - Latency budget: sum of tool spans vs SLO  

4. **Where scores live (stubs)**  
   - Langfuse scores — see `docs/integrations/langfuse.md`  
   - Phoenix annotations — see `docs/integrations/phoenix.md`  
   - For now: print a JSON line locally (`trace_id`, `pass`, `reason`) — enough for CI later  

5. **Closing the loop**  
   Fail CI on smoke eval of a recorded fixture (future). Keep human review for open-ended answers.

6. **Call to action**  
   Paste one failed-turn `trace_id` + rubric notes into Dogfooding tip.

## Assets to gather later

- [ ] Jaeger screenshot of failed `lookup_faq`  
- [ ] Example eval JSON fixture under `lab/fixtures/` (post-MVP)  

## Non-goals

Full gateway mesh; paid eval SaaS bake-off; custom OTel convention RFC.
