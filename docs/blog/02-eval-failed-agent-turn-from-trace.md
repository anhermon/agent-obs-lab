# Draft outline: Eval a failed agent turn from a trace

> Status: **outline / draft** — not a published blog post.

## Working title

*The span said it failed — now score the turn*

## Audience

Builders who have traces but no eval loop yet.

## Outline

1. **Hook**  
   A trace with a red `lookup_faq` span. Users felt a bad answer. Can we grade it offline — and can that grade show up **on the same span** as the duration waterfall?

2. **Produce a failed turn in the lab**  
   ```bash
   ./scripts/run-local.sh          # or --fanout for Phoenix too
   ./scripts/run-trace.sh
   python3 lab/agent.py --fail-faq
   cat artifacts/eval-result.json
   ```  
   Find the trace in Jaeger (wait ~2–5s): root `agent.turn` + child tool spans sharing one `trace_id`; `isError` / error text on `lookup_faq`.  
   On **`agent.turn` Tags / Logs**: `eval.pass=false`, `eval.score≈0.3333`, rubric `lab.turn.v1`, assertion events for `tools_all_ok` and `faq_answer_ok`.  
   Happy path contrast: `python3 lab/agent.py` → `eval.pass=true`, `eval.score=1`.

3. **Minimal eval rubric (`lab/eval.py`, `lab.turn.v1`)**  
   - `required_tools_present` — weather, calculate, lookup_faq all ran  
   - `tools_all_ok` — no tool returned `isError`  
   - `faq_answer_ok` — FAQ returned a non-error answer  
   - Score = fraction of assertions passed (0–1); overall pass only if all pass  

4. **Where scores live (no dual SDK)**  
   - **Primary (lab MVP):** OTLP attributes + span events on `agent.turn` — visible in Jaeger without Langfuse/Phoenix SDKs  
   - Companion JSON: `artifacts/eval-result.json` for CI / dogfood  
   - Langfuse scores — see `docs/integrations/langfuse.md` (Collector fan-out; map `eval.score` later)  
   - Phoenix annotations — see `docs/integrations/phoenix.md`  

5. **Closing the loop**  
   Fail CI on smoke eval of a recorded fixture (future). Keep human review for open-ended answers. Today: unit-test the rubric in `lab/test_eval.py`.

6. **Call to action**  
   Paste one failed-turn `trace_id` + screenshot of `eval.*` Tags/Logs into Dogfooding tip.

## Assets to gather later

- [ ] Jaeger screenshot of `agent.turn` Tags with `eval.pass` / `eval.score` (happy + `--fail-faq`)  
- [ ] Jaeger screenshot of span Logs / events named `eval.assertion`  
- [ ] Example `artifacts/eval-result.json` checked into docs (optional)  

## Non-goals

Full gateway mesh; paid eval SaaS bake-off; custom OTel convention RFC; dual-SDK scoring in the toy agent.
