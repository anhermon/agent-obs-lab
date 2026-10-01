# README screenshots

Captured by Dogfooding 2026-10-01 against fanout-capable tip `0908714` (main `3303232`).

| File | What |
|------|------|
| `jaeger-agent-turn-parent.png` | Jaeger waterfall: sole root `agent.turn` with CHILD_OF tool spans (`get_weather`, `calculate`, `lookup_faq`) on the default Jaeger path. |
| `phoenix-fanout-spans.png` | Phoenix `:6006` after `./scripts/run-local.sh --fanout` with the same span set. |

## Eval attributes (placeholders — Dogfooding re-capture)

| File | Capture when |
|------|----------------|
| `jaeger-eval-attributes.png` | Happy path `python3 lab/agent.py` — open `agent.turn` → Tags showing `eval.pass`, `eval.score`, `eval.rubric`, assertion keys |
| `jaeger-eval-fail-faq.png` | `python3 lab/agent.py --fail-faq` — same panel with `eval.pass=false` + failed `lookup_faq` child visible |

Also useful: Logs/Events panel with `eval.assertion` / `eval.score` event names.
