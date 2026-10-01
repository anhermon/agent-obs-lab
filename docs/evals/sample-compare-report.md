# Comparative eval report

**Task:** Answer the user: what is the weather in Tel Aviv, what is (28-18)*2, and how does mcp-trace help with MCP observability?

**Rubric:** `lab.compare.perf.v1` (agent performance — duration / cost / quality)

**Overall weights:** quality=0.55, latency=0.25, cost=0.2

## Performance by variant

| Variant | Model | Duration (ms) | Cost (USD) | Quality | Overall |
|---------|-------|-------------:|-----------:|--------:|--------:|
| `fast_cheap` | `stub-fast-mini` | 420 | 0.0008 | 0.5714 | 0.67 |
| `quality_first` | `stub-quality-pro` | 1850 | 0.0064 | 1.0 | 0.55 |

## Diffs (same task)

- **Duration delta:** `1430.0` ms (faster: `fast_cheap`)
- **Cost delta:** `$0.0056` (cheaper: `fast_cheap`)
- **Quality delta:** `0.4286` (better: `quality_first`)
- **Overall delta:** `0.12` (better: `fast_cheap`)

## Response quality criteria

| Criterion | `fast_cheap` | `quality_first` | Differs? |
|-----------|------|------|----------|
| `mentions_weather` | PASS | PASS | no |
| `includes_calc` | PASS | PASS | no |
| `explains_mcp_trace` | FAIL | PASS | yes |
| `actionable_tip` | FAIL | PASS | yes |

## Variant notes

- **`fast_cheap`** (Fast / cheap model stub): Smaller model stub: low latency + cost, but a terse answer that misses observability detail (lower quality).
- **`quality_first`** (Quality-first model stub): Stronger model stub: higher latency + cost, fuller answer that hits weather, calc, mcp-trace spans, and OTLP tip.

## Secondary: tool-turn rubric (`lab.turn.v1`)

_Not the headline — retained so single-turn Jaeger Tags demos stay linked._

| Variant | Turn score | Turn pass |
|---------|-----------:|-----------|
| `fast_cheap` | 1.0 | yes |
| `quality_first` | 1.0 | yes |
