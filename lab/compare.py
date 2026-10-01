#!/usr/bin/env python3
"""Comparative agent-performance evals.

Multiple variants (prompt / tool-config / model stubs) × the **same task** ×
scored criteria (duration, cost, response quality) × visible diffs.

Offline / deterministic: no Docker, no mcp-trace, no real LLM. Model cost,
latency, and answer text are stubbed per variant so CI stays green offline.
Optional ``lab.turn.v1`` tool-turn checks remain as **secondary** signals.

Usage::

    python3 lab/compare.py
    python3 lab/compare.py --out-dir artifacts --write-sample
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from lab.eval import RUBRIC_ID, evaluate_turn
    from lab.mcp_server import call_tool
except ImportError:  # running as ``python3 lab/compare.py``
    from eval import RUBRIC_ID, evaluate_turn  # type: ignore[no-redef]
    from mcp_server import call_tool  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "compare_variants.json"
COMPARE_RUBRIC_ID = "lab.compare.perf.v1"


@dataclass(frozen=True)
class QualityCriterion:
    """One response-quality check against the stubbed final answer."""

    id: str
    description: str
    must_include: tuple[str, ...]
    weight: float = 1.0


@dataclass(frozen=True)
class VariantSpec:
    """One prompt/tool-config/model stub for the shared task."""

    id: str
    label: str
    description: str
    # Deterministic performance stubs (no real LLM).
    duration_ms: float
    cost_usd: float
    final_answer: str
    # Optional tool steps → secondary lab.turn.v1 signal.
    steps: tuple[tuple[str, dict[str, Any]], ...] = ()
    fail_faq: bool = False
    model: str = "stub"


@dataclass
class VariantRow:
    """Performance + quality outcome for one variant."""

    variant_id: str
    label: str
    description: str
    model: str
    duration_ms: float
    cost_usd: float
    quality_score: float
    quality_passed: list[dict[str, Any]] = field(default_factory=list)
    overall_score: float = 0.0
    # Secondary: tool-turn rubric (not the headline).
    turn_rubric: str | None = None
    turn_score: float | None = None
    turn_passed: bool | None = None
    tools_called: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompareReport:
    """Side-by-side comparative performance report."""

    task: str
    rubric: str
    criteria: list[dict[str, Any]]
    variants: list[VariantRow]
    diffs: dict[str, Any]
    weights: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "rubric": self.rubric,
            "criteria": self.criteria,
            "weights": self.weights,
            "variants": [v.to_dict() for v in self.variants],
            "diffs": self.diffs,
        }


def _default_task() -> str:
    return (
        "Answer the user: what is the weather in Tel Aviv, what is (28-18)*2, "
        "and how does mcp-trace help with MCP observability?"
    )


def _default_criteria() -> list[QualityCriterion]:
    return [
        QualityCriterion(
            id="mentions_weather",
            description="Answer mentions Tel Aviv weather / temperature",
            must_include=("tel aviv", "28"),
        ),
        QualityCriterion(
            id="includes_calc",
            description="Answer includes the calculation result 20",
            must_include=("20",),
        ),
        QualityCriterion(
            id="explains_mcp_trace",
            description="Answer explains mcp-trace (proxy / OTel spans)",
            must_include=("mcp-trace", "span"),
        ),
        QualityCriterion(
            id="actionable_tip",
            description="Answer gives an actionable tip (OTLP / Jaeger / export)",
            must_include=("otlp",),
            weight=0.5,
        ),
    ]


def _default_variants() -> list[VariantSpec]:
    weather = ("get_weather", {"city": "Tel Aviv"})
    calc = ("calculate", {"expression": "(28 - 18) * 2"})
    faq_ok = ("lookup_faq", {"topic": "mcp-trace"})
    return [
        VariantSpec(
            id="fast_cheap",
            label="Fast / cheap model stub",
            description=(
                "Smaller model stub: low latency + cost, but a terse answer "
                "that misses observability detail (lower quality)."
            ),
            duration_ms=420.0,
            cost_usd=0.0008,
            final_answer=(
                "Tel Aviv is about 28C. (28-18)*2 = 20. "
                "mcp-trace sits in front of MCP servers."
            ),
            steps=(weather, calc, faq_ok),
            model="stub-fast-mini",
        ),
        VariantSpec(
            id="quality_first",
            label="Quality-first model stub",
            description=(
                "Stronger model stub: higher latency + cost, fuller answer "
                "that hits weather, calc, mcp-trace spans, and OTLP tip."
            ),
            duration_ms=1850.0,
            cost_usd=0.0064,
            final_answer=(
                "Weather in Tel Aviv: 28°C and clear. "
                "(28 - 18) * 2 = 20. "
                "Put mcp-trace in front of any MCP server so every tools/call "
                "becomes an OTel span; export OTLP to Jaeger to inspect traces."
            ),
            steps=(weather, calc, faq_ok),
            model="stub-quality-pro",
        ),
    ]


def _default_weights() -> dict[str, float]:
    """Weights for overall_score in [0, 1] (higher is better)."""
    return {
        "quality": 0.55,
        "latency": 0.25,  # faster → higher contribution
        "cost": 0.20,  # cheaper → higher contribution
    }


def load_fixture(
    path: Path | None = None,
) -> tuple[str, list[QualityCriterion], list[VariantSpec], dict[str, float]]:
    """Load task, criteria, variants, weights from JSON (or built-ins)."""
    fixture = path or DEFAULT_FIXTURE
    if not fixture.is_file():
        return _default_task(), _default_criteria(), _default_variants(), _default_weights()

    data = json.loads(fixture.read_text(encoding="utf-8"))
    task = str(data.get("task") or _default_task())
    weights = dict(_default_weights())
    weights.update({k: float(v) for k, v in (data.get("weights") or {}).items()})

    criteria: list[QualityCriterion] = []
    for raw in data.get("criteria") or []:
        criteria.append(
            QualityCriterion(
                id=str(raw["id"]),
                description=str(raw.get("description") or raw["id"]),
                must_include=tuple(str(x).lower() for x in (raw.get("must_include") or [])),
                weight=float(raw.get("weight", 1.0)),
            )
        )
    if not criteria:
        criteria = _default_criteria()

    variants: list[VariantSpec] = []
    for raw in data.get("variants") or []:
        steps = tuple(
            (str(s["tool"]), dict(s.get("arguments") or {}))
            for s in (raw.get("steps") or [])
        )
        variants.append(
            VariantSpec(
                id=str(raw["id"]),
                label=str(raw.get("label") or raw["id"]),
                description=str(raw.get("description") or ""),
                duration_ms=float(raw["duration_ms"]),
                cost_usd=float(raw["cost_usd"]),
                final_answer=str(raw["final_answer"]),
                steps=steps,
                fail_faq=bool(raw.get("fail_faq", False)),
                model=str(raw.get("model") or "stub"),
            )
        )
    if len(variants) < 2:
        raise ValueError(f"need ≥2 variants in {fixture}, got {len(variants)}")
    return task, criteria, variants, weights


def score_response_quality(
    answer: str, criteria: list[QualityCriterion]
) -> tuple[float, list[dict[str, Any]]]:
    """Score final answer against quality criteria (substring checks)."""
    text = answer.lower()
    outcomes: list[dict[str, Any]] = []
    total_w = sum(c.weight for c in criteria) or 1.0
    earned = 0.0
    for c in criteria:
        missing = [t for t in c.must_include if t.lower() not in text]
        passed = not missing
        if passed:
            earned += c.weight
        outcomes.append(
            {
                "id": c.id,
                "description": c.description,
                "passed": passed,
                "weight": c.weight,
                "missing": missing,
            }
        )
    return round(earned / total_w, 4), outcomes


def _rpc_body(tool_result: dict[str, Any]) -> dict[str, Any]:
    return {"result": tool_result}


def _secondary_turn(spec: VariantSpec) -> tuple[float | None, bool | None, list[str]]:
    """Optional lab.turn.v1 from in-process tool calls (secondary signal)."""
    if not spec.steps:
        return None, None, []
    results: list[tuple[str, dict[str, Any] | None]] = []
    for name, args in spec.steps:
        results.append((name, _rpc_body(call_tool(name, args))))
    ev = evaluate_turn(results, fail_faq=spec.fail_faq, rubric=RUBRIC_ID)
    return ev.score, ev.passed, [n for n, _ in results]


def _normalize_better(values: list[float], *, higher_is_better: bool) -> list[float]:
    """Min-max normalize to [0, 1]. Ties → 1.0 for all."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]
    if higher_is_better:
        return [(v - lo) / (hi - lo) for v in values]
    return [(hi - v) / (hi - lo) for v in values]


def _overall_scores(
    rows_partial: list[tuple[float, float, float]],
    weights: dict[str, float],
) -> list[float]:
    """Combine quality / latency / cost into overall [0, 1] (higher better)."""
    qualities = [p[0] for p in rows_partial]
    durations = [p[1] for p in rows_partial]
    costs = [p[2] for p in rows_partial]
    q_n = _normalize_better(qualities, higher_is_better=True)
    # Already absolute quality in [0,1]; prefer raw quality, blend with relative:
    q_blend = [0.7 * q + 0.3 * n for q, n in zip(qualities, q_n, strict=True)]
    lat_n = _normalize_better(durations, higher_is_better=False)
    cost_n = _normalize_better(costs, higher_is_better=False)
    wq = float(weights.get("quality", 0.55))
    wl = float(weights.get("latency", 0.25))
    wc = float(weights.get("cost", 0.20))
    wsum = wq + wl + wc or 1.0
    out: list[float] = []
    for i in range(len(rows_partial)):
        score = (wq * q_blend[i] + wl * lat_n[i] + wc * cost_n[i]) / wsum
        out.append(round(score, 4))
    return out


def run_variant(
    spec: VariantSpec, criteria: list[QualityCriterion]
) -> VariantRow:
    quality, q_detail = score_response_quality(spec.final_answer, criteria)
    turn_score, turn_passed, tools = _secondary_turn(spec)
    return VariantRow(
        variant_id=spec.id,
        label=spec.label,
        description=spec.description,
        model=spec.model,
        duration_ms=spec.duration_ms,
        cost_usd=spec.cost_usd,
        quality_score=quality,
        quality_passed=q_detail,
        overall_score=0.0,  # filled after all variants
        turn_rubric=RUBRIC_ID if spec.steps else None,
        turn_score=turn_score,
        turn_passed=turn_passed,
        tools_called=tools,
    )


def _build_diffs(rows: list[VariantRow]) -> dict[str, Any]:
    if not rows:
        return {}
    by_id = {r.variant_id: r for r in rows}
    durations = {r.variant_id: r.duration_ms for r in rows}
    costs = {r.variant_id: r.cost_usd for r in rows}
    qualities = {r.variant_id: r.quality_score for r in rows}
    overalls = {r.variant_id: r.overall_score for r in rows}

    # Quality criterion matrix
    crit_ids = [c["id"] for c in rows[0].quality_passed]
    quality_matrix: list[dict[str, Any]] = []
    for cid in crit_ids:
        by_variant: dict[str, bool] = {}
        for r in rows:
            hit = next((c for c in r.quality_passed if c["id"] == cid), None)
            by_variant[r.variant_id] = bool(hit and hit["passed"])
        quality_matrix.append(
            {
                "criterion": cid,
                "by_variant": by_variant,
                "differs": len(set(by_variant.values())) > 1,
            }
        )

    return {
        "duration_ms": {
            "by_variant": durations,
            "delta": round(max(durations.values()) - min(durations.values()), 4),
            "winner": min(by_id.values(), key=lambda r: r.duration_ms).variant_id,
        },
        "cost_usd": {
            "by_variant": costs,
            "delta": round(max(costs.values()) - min(costs.values()), 6),
            "winner": min(by_id.values(), key=lambda r: r.cost_usd).variant_id,
        },
        "quality_score": {
            "by_variant": qualities,
            "delta": round(max(qualities.values()) - min(qualities.values()), 4),
            "winner": max(by_id.values(), key=lambda r: r.quality_score).variant_id,
        },
        "overall_score": {
            "by_variant": overalls,
            "delta": round(max(overalls.values()) - min(overalls.values()), 4),
            "winner": max(by_id.values(), key=lambda r: r.overall_score).variant_id,
        },
        "quality_criteria": quality_matrix,
    }


def compare_variants(
    *,
    fixture_path: Path | None = None,
) -> CompareReport:
    """Run all variants on the shared task and build a performance report."""
    task, criteria, variants, weights = load_fixture(fixture_path)
    rows = [run_variant(spec, criteria) for spec in variants]
    overalls = _overall_scores(
        [(r.quality_score, r.duration_ms, r.cost_usd) for r in rows],
        weights,
    )
    for row, overall in zip(rows, overalls, strict=True):
        row.overall_score = overall

    return CompareReport(
        task=task,
        rubric=COMPARE_RUBRIC_ID,
        criteria=[
            {
                "id": c.id,
                "description": c.description,
                "must_include": list(c.must_include),
                "weight": c.weight,
            }
            for c in criteria
        ],
        variants=rows,
        diffs=_build_diffs(rows),
        weights=weights,
    )


def render_markdown(report: CompareReport) -> str:
    """Human-readable performance table + diffs."""
    lines: list[str] = [
        "# Comparative eval report",
        "",
        f"**Task:** {report.task}",
        "",
        f"**Rubric:** `{report.rubric}` (agent performance — duration / cost / quality)",
        "",
        f"**Overall weights:** quality={report.weights.get('quality')}, "
        f"latency={report.weights.get('latency')}, cost={report.weights.get('cost')}",
        "",
        "## Performance by variant",
        "",
        "| Variant | Model | Duration (ms) | Cost (USD) | Quality | Overall |",
        "|---------|-------|-------------:|-----------:|--------:|--------:|",
    ]
    for v in report.variants:
        lines.append(
            f"| `{v.variant_id}` | `{v.model}` | {v.duration_ms:g} | "
            f"{v.cost_usd:.4f} | {v.quality_score} | {v.overall_score} |"
        )

    d = report.diffs
    lines.extend(
        [
            "",
            "## Diffs (same task)",
            "",
            f"- **Duration delta:** `{d.get('duration_ms', {}).get('delta')}` ms "
            f"(faster: `{d.get('duration_ms', {}).get('winner')}`)",
            f"- **Cost delta:** `${d.get('cost_usd', {}).get('delta')}` "
            f"(cheaper: `{d.get('cost_usd', {}).get('winner')}`)",
            f"- **Quality delta:** `{d.get('quality_score', {}).get('delta')}` "
            f"(better: `{d.get('quality_score', {}).get('winner')}`)",
            f"- **Overall delta:** `{d.get('overall_score', {}).get('delta')}` "
            f"(better: `{d.get('overall_score', {}).get('winner')}`)",
            "",
            "## Response quality criteria",
            "",
        ]
    )
    header_ids = [v.variant_id for v in report.variants]
    lines.append(
        "| Criterion | " + " | ".join(f"`{i}`" for i in header_ids) + " | Differs? |"
    )
    lines.append(
        "|-----------|" + "|".join(["------"] * len(header_ids)) + "|----------|"
    )
    for row in d.get("quality_criteria") or []:
        cells = [
            "PASS" if row["by_variant"].get(vid) else "FAIL" for vid in header_ids
        ]
        differs = "yes" if row["differs"] else "no"
        lines.append(
            f"| `{row['criterion']}` | " + " | ".join(cells) + f" | {differs} |"
        )

    lines.extend(
        [
            "",
            "## Variant notes",
            "",
        ]
    )
    for v in report.variants:
        lines.append(f"- **`{v.variant_id}`** ({v.label}): {v.description}")

    # Secondary tool-turn signal (not headline)
    if any(v.turn_score is not None for v in report.variants):
        lines.extend(
            [
                "",
                "## Secondary: tool-turn rubric (`lab.turn.v1`)",
                "",
                "_Not the headline — retained so single-turn Jaeger Tags demos stay linked._",
                "",
                "| Variant | Turn score | Turn pass |",
                "|---------|-----------:|-----------|",
            ]
        )
        for v in report.variants:
            if v.turn_score is None:
                lines.append(f"| `{v.variant_id}` | — | — |")
            else:
                mark = "yes" if v.turn_passed else "no"
                lines.append(f"| `{v.variant_id}` | {v.turn_score} | {mark} |")

    lines.append("")
    return "\n".join(lines)


def write_compare_artifacts(
    report: CompareReport,
    out_dir: Path,
    *,
    also_sample: Path | None = None,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "compare-report.json"
    md_path = out_dir / "compare-report.md"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    md_text = render_markdown(report)
    md_path.write_text(md_text, encoding="utf-8")
    if also_sample is not None:
        also_sample.parent.mkdir(parents=True, exist_ok=True)
        also_sample.write_text(md_text, encoding="utf-8")
    return json_path, md_path


def default_out_dir(repo_root: Path | None = None) -> Path:
    return (repo_root or REPO_ROOT) / "artifacts"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Comparative agent-performance evals (offline)"
    )
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--write-sample",
        action="store_true",
        help="Also refresh docs/evals/sample-compare-report.md",
    )
    args = parser.parse_args(argv)

    report = compare_variants(fixture_path=args.fixture)
    out_dir = args.out_dir or default_out_dir()
    sample = (
        REPO_ROOT / "docs" / "evals" / "sample-compare-report.md"
        if args.write_sample
        else None
    )
    json_path, md_path = write_compare_artifacts(report, out_dir, also_sample=sample)

    print("=== comparative eval (performance) ===")
    print(f"task: {report.task}")
    print(f"rubric: {report.rubric}")
    print(f"variants: {len(report.variants)}")
    for v in report.variants:
        print(
            f"- {v.variant_id}: duration={v.duration_ms:g}ms cost=${v.cost_usd:.4f} "
            f"quality={v.quality_score} overall={v.overall_score}"
        )
    d = report.diffs
    print(
        f"diffs: durationΔ={d['duration_ms']['delta']}ms "
        f"costΔ=${d['cost_usd']['delta']} "
        f"qualityΔ={d['quality_score']['delta']} "
        f"overallΔ={d['overall_score']['delta']}"
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    if sample:
        print(f"wrote {sample}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
