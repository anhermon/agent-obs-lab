"""Turn-level eval rubric for agent-obs-lab.

Scores a completed multi-tool turn from MCP tool results / ``isError`` flags
(no LLM judge). Outcomes attach to the ``agent.turn`` span as attributes and
events, and optionally land in ``artifacts/eval-result.json``.

Keep this path OTLP-only — no Langfuse/Phoenix SDK in the toy agent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RUBRIC_ID = "lab.turn.v1"
REQUIRED_TOOLS = ("get_weather", "calculate", "lookup_faq")


@dataclass(frozen=True)
class AssertionOutcome:
    """One rubric check with pass/fail + expected vs actual snippets."""

    name: str
    passed: bool
    expected: str
    actual: str
    weight: float = 1.0


@dataclass
class EvalResult:
    """Aggregate score for one agent turn."""

    rubric: str
    passed: bool
    score: float
    assertions: list[AssertionOutcome] = field(default_factory=list)
    trace_id: str | None = None
    fail_faq: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rubric": self.rubric,
            "pass": self.passed,
            "score": self.score,
            "trace_id": self.trace_id,
            "fail_faq": self.fail_faq,
            "assertions": [asdict(a) for a in self.assertions],
        }


def _tool_text(msg: dict[str, Any] | None) -> tuple[bool, str]:
    """Return (is_error, text_snippet) from a tools/call JSON-RPC body."""
    if msg is None:
        return True, "(empty response)"
    result = msg.get("result") or {}
    is_error = bool(result.get("isError"))
    text = ""
    content = result.get("content") or []
    if content and isinstance(content, list):
        text = str(content[0].get("text", ""))
    snippet = text if len(text) <= 160 else text[:157] + "..."
    if not snippet:
        snippet = "(no text content)"
    return is_error, snippet


def evaluate_turn(
    results: list[tuple[str, dict[str, Any] | None]],
    *,
    fail_faq: bool = False,
    trace_id: str | None = None,
    rubric: str = RUBRIC_ID,
) -> EvalResult:
    """Score a completed turn from ``(tool_name, rpc_body)`` pairs.

    Rubric ``lab.turn.v1``:
    - ``required_tools_present`` — weather, calculate, lookup_faq all ran
    - ``tools_all_ok`` — no tool returned ``isError``
    - ``faq_answer_ok`` — ``lookup_faq`` succeeded with a non-empty answer
    """
    by_name: dict[str, dict[str, Any] | None] = {name: msg for name, msg in results}
    called = set(by_name)

    missing = [t for t in REQUIRED_TOOLS if t not in called]
    present_ok = not missing
    called_label = ",".join(n for n, _ in results) if results else "(none)"
    assertions: list[AssertionOutcome] = [
        AssertionOutcome(
            name="required_tools_present",
            passed=present_ok,
            expected=",".join(REQUIRED_TOOLS),
            actual=called_label if present_ok else f"missing: {','.join(missing)}",
        )
    ]

    errored: list[str] = []
    snippets: dict[str, str] = {}
    for name, msg in results:
        is_err, snippet = _tool_text(msg)
        snippets[name] = snippet
        if is_err:
            errored.append(name)

    tools_ok = present_ok and not errored
    assertions.append(
        AssertionOutcome(
            name="tools_all_ok",
            passed=tools_ok,
            expected="all tools isError=false",
            actual=(
                "all ok"
                if tools_ok
                else f"errors on: {','.join(errored) or '(incomplete)'}"
            ),
        )
    )

    faq_msg = by_name.get("lookup_faq")
    faq_err, faq_text = _tool_text(faq_msg) if "lookup_faq" in by_name else (True, "(not called)")
    faq_ok = "lookup_faq" in by_name and not faq_err and bool(faq_text.strip())
    assertions.append(
        AssertionOutcome(
            name="faq_answer_ok",
            passed=faq_ok,
            expected="lookup_faq returns a non-error answer",
            actual=faq_text,
        )
    )

    total_w = sum(a.weight for a in assertions) or 1.0
    score = sum(a.weight for a in assertions if a.passed) / total_w
    # Avoid float noise in JSON / Jaeger (0, 1/3, 2/3, 1)
    score = round(score, 4)
    passed = all(a.passed for a in assertions)

    return EvalResult(
        rubric=rubric,
        passed=passed,
        score=score,
        assertions=assertions,
        trace_id=trace_id,
        fail_faq=fail_faq,
    )


def eval_to_otlp_attributes(result: EvalResult) -> list[dict[str, Any]]:
    """OTLP/HTTP JSON attribute list for the ``agent.turn`` span."""
    attrs: list[dict[str, Any]] = [
        {"key": "eval.rubric", "value": {"stringValue": result.rubric}},
        {"key": "eval.pass", "value": {"boolValue": result.passed}},
        {"key": "eval.score", "value": {"doubleValue": result.score}},
        {
            "key": "eval.assertion_count",
            "value": {"intValue": str(len(result.assertions))},
        },
    ]
    for a in result.assertions:
        prefix = f"eval.assertion.{a.name}"
        attrs.append({"key": f"{prefix}.pass", "value": {"boolValue": a.passed}})
        attrs.append({"key": f"{prefix}.expected", "value": {"stringValue": a.expected}})
        attrs.append({"key": f"{prefix}.actual", "value": {"stringValue": a.actual}})
    return attrs


def eval_to_otlp_events(result: EvalResult, time_ns: int) -> list[dict[str, Any]]:
    """One span event per assertion so Jaeger Tags/Logs show pass|fail clearly."""
    events: list[dict[str, Any]] = []
    for a in result.assertions:
        events.append(
            {
                "timeUnixNano": str(time_ns),
                "name": "eval.assertion",
                "attributes": [
                    {"key": "eval.assertion.name", "value": {"stringValue": a.name}},
                    {"key": "eval.assertion.pass", "value": {"boolValue": a.passed}},
                    {
                        "key": "eval.assertion.expected",
                        "value": {"stringValue": a.expected},
                    },
                    {
                        "key": "eval.assertion.actual",
                        "value": {"stringValue": a.actual},
                    },
                    {"key": "eval.rubric", "value": {"stringValue": result.rubric}},
                ],
            }
        )
    # Summary event mirrors Langfuse-style score attachment without a second SDK.
    events.append(
        {
            "timeUnixNano": str(time_ns),
            "name": "eval.score",
            "attributes": [
                {"key": "eval.rubric", "value": {"stringValue": result.rubric}},
                {"key": "eval.pass", "value": {"boolValue": result.passed}},
                {"key": "eval.score", "value": {"doubleValue": result.score}},
            ],
        }
    )
    return events


def write_eval_artifact(result: EvalResult, path: Path) -> Path:
    """Write ``artifacts/eval-result.json`` (or ``path``) for CI / dogfood."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def default_artifact_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parent.parent
    return root / "artifacts" / "eval-result.json"
