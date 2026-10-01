"""Unit tests for turn-level eval rubric (no network / mcp-trace)."""

from __future__ import annotations

import json
from pathlib import Path

from lab.eval import (
    RUBRIC_ID,
    eval_to_otlp_attributes,
    eval_to_otlp_events,
    evaluate_turn,
    write_eval_artifact,
)


def _ok(text: str) -> dict:
    return {"result": {"content": [{"type": "text", "text": text}]}}


def _err(text: str) -> dict:
    return {"result": {"content": [{"type": "text", "text": text}], "isError": True}}


def test_happy_path_passes():
    results = [
        ("get_weather", _ok("Weather in Tel Aviv: 28°C")),
        ("calculate", _ok("(28 - 18) * 2 = 20.0")),
        ("lookup_faq", _ok("Put mcp-trace in front of any MCP server")),
    ]
    ev = evaluate_turn(results, trace_id="abc")
    assert ev.rubric == RUBRIC_ID
    assert ev.passed is True
    assert ev.score == 1.0
    assert all(a.passed for a in ev.assertions)
    assert ev.trace_id == "abc"


def test_fail_faq_scores_partial():
    results = [
        ("get_weather", _ok("ok")),
        ("calculate", _ok("1 = 1")),
        ("lookup_faq", _err("no FAQ for topic='does-not-exist'")),
    ]
    ev = evaluate_turn(results, fail_faq=True)
    assert ev.passed is False
    assert ev.fail_faq is True
    by_name = {a.name: a for a in ev.assertions}
    assert by_name["required_tools_present"].passed is True
    assert by_name["tools_all_ok"].passed is False
    assert by_name["faq_answer_ok"].passed is False
    assert ev.score == round(1 / 3, 4)


def test_otlp_attributes_and_events_include_eval_keys():
    results = [
        ("get_weather", _ok("ok")),
        ("calculate", _ok("ok")),
        ("lookup_faq", _ok("answer")),
    ]
    ev = evaluate_turn(results)
    attrs = {a["key"]: a["value"] for a in eval_to_otlp_attributes(ev)}
    assert attrs["eval.pass"] == {"boolValue": True}
    assert attrs["eval.score"] == {"doubleValue": 1.0}
    assert attrs["eval.rubric"] == {"stringValue": RUBRIC_ID}
    assert "eval.assertion.faq_answer_ok.pass" in attrs

    events = eval_to_otlp_events(ev, time_ns=123)
    names = [e["name"] for e in events]
    assert names.count("eval.assertion") == 3
    assert "eval.score" in names
    assert events[0]["timeUnixNano"] == "123"


def test_write_eval_artifact(tmp_path: Path):
    results = [("get_weather", _ok("x")), ("calculate", _ok("y")), ("lookup_faq", _ok("z"))]
    ev = evaluate_turn(results, trace_id="deadbeef")
    out = write_eval_artifact(ev, tmp_path / "eval-result.json")
    data = json.loads(out.read_text())
    assert data["pass"] is True
    assert data["score"] == 1.0
    assert data["trace_id"] == "deadbeef"
    assert len(data["assertions"]) == 3
