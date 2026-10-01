# README screenshots

| File | What |
|------|------|
| `jaeger-agent-turn-parent.png` | Jaeger waterfall: sole root `agent.turn` + tool CHILD_OF (default path). |
| `phoenix-fanout-spans.png` | Phoenix `:6006` after `--fanout` with the same span set. |
| `jaeger-eval-attributes.png` | Dogfood: expanded Tags on happy-path `agent.turn` (`eval.score=1`, `eval.pass=true`). |
| `jaeger-eval-fail-faq.png` | Dogfood: expanded Tags on `--fail-faq` (`eval.score=0.3333`, `eval.pass=false`). |
| `jaeger-eval-attributes-detail.png` | Optional crop of happy-path eval Tags. |
| `jaeger-eval-fail-faq-detail.png` | Optional crop of fail-faq eval Tags. |

Captures from Dogfooding 2026-10-01 on PR #4 tip `06ca681`. Expand Tags in Jaeger — the summary line truncates until expanded. Waterfall accent color is not authoritative for `tools_all_ok`; use Tags.
