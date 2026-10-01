# README screenshots

| File | What |
|------|------|
| `jaeger-agent-turn-parent.png` | Jaeger waterfall: sole root `agent.turn` + tool CHILD_OF (default path). |
| `phoenix-fanout-spans.png` | Phoenix `:6006` after `--fanout` with the same span set. |
| `jaeger-eval-attributes-detail.png` | README primary: happy-path `agent.turn` Tags crop (`eval.score=1`, `eval.pass=true`). |
| `jaeger-eval-fail-faq-detail.png` | README primary: `--fail-faq` Tags crop (`eval.score=0.3333`, `eval.pass=false`). |
| `jaeger-eval-attributes.png` | Full expanded Tags panel (happy path); kept for reference. |
| `jaeger-eval-fail-faq.png` | Full expanded Tags panel (`--fail-faq`); kept for reference. |
| `compare-evals-report.png` | README primary: comparative performance table (duration / cost / quality / overall) from `lab/compare.py`. |

Captures from Dogfooding 2026-10-01 on PR #4 tip `06ca681`. Expand Tags in Jaeger — the summary line truncates until expanded. Waterfall accent color is not authoritative for `tools_all_ok`; use Tags.
