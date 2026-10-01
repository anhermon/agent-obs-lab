"""Unit tests for comparative performance evals (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from lab.compare import (
    DEFAULT_FIXTURE,
    compare_variants,
    load_fixture,
    render_markdown,
    score_response_quality,
    write_compare_artifacts,
)


def test_fixture_has_performance_variants():
    task, criteria, variants, weights = load_fixture(DEFAULT_FIXTURE)
    assert "mcp-trace" in task.lower() or "tel aviv" in task.lower()
    assert len(variants) >= 2
    assert len(criteria) >= 2
    assert "quality" in weights
    ids = {v.id for v in variants}
    assert "fast_cheap" in ids
    assert "quality_first" in ids
    # Headline fields present on every variant
    for v in variants:
        assert v.duration_ms > 0
        assert v.cost_usd > 0
        assert v.final_answer.strip()


def test_quality_scoring_differs_on_fixture_answers():
    _, criteria, variants, _ = load_fixture(DEFAULT_FIXTURE)
    by_id = {v.id: v for v in variants}
    q_fast, detail_fast = score_response_quality(by_id["fast_cheap"].final_answer, criteria)
    q_qual, detail_qual = score_response_quality(
        by_id["quality_first"].final_answer, criteria
    )
    assert q_qual > q_fast
    assert q_qual == 1.0
    failed = [d["id"] for d in detail_fast if not d["passed"]]
    assert "explains_mcp_trace" in failed or "actionable_tip" in failed
    assert all(d["passed"] for d in detail_qual)


def test_compare_performance_diffs():
    report = compare_variants()
    assert len(report.variants) >= 2
    assert report.rubric == "lab.compare.perf.v1"

    by_id = {v.variant_id: v for v in report.variants}
    assert by_id["fast_cheap"].duration_ms < by_id["quality_first"].duration_ms
    assert by_id["fast_cheap"].cost_usd < by_id["quality_first"].cost_usd
    assert by_id["fast_cheap"].quality_score < by_id["quality_first"].quality_score

    diffs = report.diffs
    assert diffs["duration_ms"]["delta"] > 0
    assert diffs["cost_usd"]["delta"] > 0
    assert diffs["quality_score"]["delta"] > 0
    assert diffs["duration_ms"]["winner"] == "fast_cheap"
    assert diffs["cost_usd"]["winner"] == "fast_cheap"
    assert diffs["quality_score"]["winner"] == "quality_first"

    differing = [c for c in diffs["quality_criteria"] if c["differs"]]
    assert differing, "expected at least one quality criterion to differ"


def test_write_compare_artifacts(tmp_path: Path):
    report = compare_variants()
    sample = tmp_path / "sample.md"
    json_path, md_path = write_compare_artifacts(
        report, tmp_path / "out", also_sample=sample
    )
    data = json.loads(json_path.read_text())
    assert "duration_ms" in data["diffs"]
    assert "cost_usd" in data["diffs"]
    assert "quality_score" in data["diffs"]
    assert len(data["variants"]) >= 2
    md = md_path.read_text()
    assert "Performance by variant" in md
    assert "Duration (ms)" in md
    assert "Cost (USD)" in md
    assert "Quality" in md
    assert "Overall" in md
    assert "fast_cheap" in md
    assert sample.read_text() == md
    assert "lab.compare.perf.v1" in render_markdown(report)
