#!/usr/bin/env python3
"""Toy multi-tool agent for agent-obs-lab.

Deterministic (no LLM key required): plans a short query, then issues ≥2 MCP
tools/call requests through mcp-trace.

mcp-trace --stdio exposes **Streamable HTTP** on POST / (not legacy SSE).
The agent speaks that transport so every tools/call becomes an OTel span.

Turn-level correlation (blog 02 readiness): the agent opens a synthetic
``agent.turn`` root span (OTLP/HTTP JSON, stdlib only — no Langfuse/Phoenix
SDK) and injects W3C ``traceparent`` on every proxy request so mcp-trace
tool spans become children of the same ``trace_id``.

Eval outcomes (pass/fail, score, rubric, assertion expected vs actual) attach
to ``agent.turn`` as span attributes + events and land in
``artifacts/eval-result.json`` — visible in Jaeger without a second SDK.

Usage:
  python lab/agent.py                  # talk to http://localhost:8001
  python lab/agent.py --proxy URL
  python lab/agent.py --fail-faq       # force a failed tool turn for eval demos
  python lab/agent.py --no-turn-span   # skip parent span export (tools still run)
  python lab/agent.py --no-eval-artifact  # skip writing artifacts/eval-result.json
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from lab.eval import (
        EvalResult,
        default_artifact_path,
        eval_to_otlp_attributes,
        eval_to_otlp_events,
        evaluate_turn,
        write_eval_artifact,
    )
except ImportError:  # python lab/agent.py without package on PYTHONPATH
    from eval import (  # type: ignore[no-redef]
        EvalResult,
        default_artifact_path,
        eval_to_otlp_attributes,
        eval_to_otlp_events,
        evaluate_turn,
        write_eval_artifact,
    )


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _new_ids() -> tuple[str, str]:
    """Return (trace_id_hex32, span_id_hex16) for W3C Trace Context."""
    return secrets.token_hex(16), secrets.token_hex(8)


def _traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    flags = "01" if sampled else "00"
    return f"00-{trace_id}-{span_id}-{flags}"


def _post_rpc(
    url: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """POST one JSON-RPC message. Returns (body_json_or_None, session_id)."""
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — local lab proxy
        new_sid = resp.headers.get("Mcp-Session-Id") or session_id
        raw = resp.read().decode("utf-8", errors="replace").strip()
        if not raw:
            return None, new_sid
        # Streamable HTTP may return a single JSON object or SSE-framed data.
        if raw.startswith("{"):
            return json.loads(raw), new_sid
        # Best-effort: last data: {...} line in an SSE body
        found = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                chunk = line[len("data:") :].strip()
                if chunk.startswith("{"):
                    found = json.loads(chunk)
        return found, new_sid


def _export_turn_span(
    *,
    otlp_http: str,
    service_name: str,
    trace_id: str,
    span_id: str,
    start_ns: int,
    end_ns: int,
    fail_faq: bool,
    failed: bool,
    eval_result: EvalResult | None = None,
) -> None:
    """Export a root ``agent.turn`` span via OTLP/HTTP JSON (no OTel SDK).

    When ``eval_result`` is provided, attach ``eval.*`` attributes and
    ``eval.assertion`` / ``eval.score`` events so Jaeger shows pass|fail
    and score next to (not only) duration.
    """
    status_code = 2 if failed else 1  # OTLP: 1=OK, 2=ERROR
    status: dict[str, Any] = {"code": status_code}
    if failed:
        status["message"] = "one or more tools returned isError"
    attributes: list[dict[str, Any]] = [
        {
            "key": "agent.fail_faq",
            "value": {"boolValue": fail_faq},
        },
        {
            "key": "agent.tools",
            "value": {
                "stringValue": "get_weather,calculate,lookup_faq"
            },
        },
    ]
    events: list[dict[str, Any]] = []
    if eval_result is not None:
        attributes.extend(eval_to_otlp_attributes(eval_result))
        events.extend(eval_to_otlp_events(eval_result, end_ns))
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": "agent.turn",
        "kind": 1,  # INTERNAL
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attributes,
        "status": status,
    }
    if events:
        span["events"] = events
    body = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "agent-obs-lab-agent", "version": "0.1.0"},
                        "spans": [span],
                    }
                ],
            }
        ]
    }
    endpoint = otlp_http.rstrip("/") + "/v1/traces"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 — local OTLP
            resp.read()
        _log(f"exported agent.turn span trace_id={trace_id}")
        if eval_result is not None:
            _log(
                f"eval rubric={eval_result.rubric} pass={eval_result.passed} "
                f"score={eval_result.score}"
            )
    except urllib.error.URLError as exc:
        _log(f"turn span export skipped ({endpoint}): {exc}")
        _log("Tool spans may still appear; parent span needs OTLP/HTTP :4318.")


class McpStreamableClient:
    """Minimal MCP client for Streamable HTTP (mcp-trace --stdio front door)."""

    def __init__(self, proxy: str, traceparent: str | None = None) -> None:
        self.base = proxy.rstrip("/")
        self.url = self.base + "/"
        self.session_id: str | None = None
        self._next_id = 1
        self._traceparent = traceparent

    def _headers(self) -> dict[str, str] | None:
        if not self._traceparent:
            return None
        return {"traceparent": self._traceparent}

    def connect(self) -> None:
        _log(f"connecting Streamable HTTP {self.url}")
        result = self.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent-obs-lab-agent", "version": "0.1.0"},
            },
        )
        if result is None:
            raise RuntimeError("initialize returned empty body")
        # notifications/initialized has no id
        _post_rpc(
            self.url,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            self.session_id,
            self._headers(),
        )

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        req_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        _log(f"→ {method} {json.dumps(params)[:120]}")
        body, self.session_id = _post_rpc(self.url, payload, self.session_id, self._headers())
        if body is not None:
            _log(f"← {json.dumps(body)[:200]}")
        return body

    def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        return self.call("tools/call", {"name": name, "arguments": arguments})


def run_turn(
    proxy: str,
    fail_faq: bool = False,
    *,
    emit_turn_span: bool = True,
    otlp_http: str = "http://localhost:4318",
    service_name: str = "agent-obs-lab",
    write_artifact: bool = True,
    artifact_path: Path | None = None,
) -> int:
    """Run one multi-tool agent turn. Returns process exit code.

    Exit codes: 0 = tools ok + eval pass; 1 = tool/eval failure; 2 = infra error.
    """
    trace_id, turn_span_id = _new_ids()
    tp = _traceparent(trace_id, turn_span_id) if emit_turn_span else None
    if tp:
        _log(f"turn traceparent={tp}")
    client = McpStreamableClient(proxy, traceparent=tp)
    start_ns = time.time_ns()
    failed = False
    eval_result: EvalResult | None = None
    results: list[tuple[str, dict[str, Any] | None]] = []
    try:
        client.connect()
        steps = [
            ("get_weather", {"city": "Tel Aviv"}),
            ("calculate", {"expression": "(28 - 18) * 2"}),
        ]
        if fail_faq:
            steps.append(("lookup_faq", {"topic": "does-not-exist"}))
        else:
            steps.append(("lookup_faq", {"topic": "mcp-trace"}))

        for name, args in steps:
            msg = client.tools_call(name, args)
            results.append((name, msg))
            time.sleep(0.05)

        print("=== agent turn complete ===")
        for name, msg in results:
            if msg is None:
                print(f"- {name}: (empty response; check Jaeger for the span)")
                continue
            result = msg.get("result") or {}
            err = result.get("isError")
            text = ""
            content = result.get("content") or []
            if content and isinstance(content, list):
                text = content[0].get("text", "")
            flag = "ERROR" if err else "ok"
            print(f"- {name}: [{flag}] {text}")

        failed = any((m or {}).get("result", {}).get("isError") for _, m in results if m)
        eval_result = evaluate_turn(results, fail_faq=fail_faq, trace_id=trace_id)
        print("=== eval ===")
        print(
            f"rubric={eval_result.rubric} pass={eval_result.passed} "
            f"score={eval_result.score}"
        )
        for a in eval_result.assertions:
            mark = "PASS" if a.passed else "FAIL"
            print(f"- [{mark}] {a.name}: expected={a.expected!r} actual={a.actual!r}")
        if write_artifact:
            out = write_eval_artifact(
                eval_result, artifact_path or default_artifact_path()
            )
            _log(f"wrote eval artifact {out}")
        # Prefer eval failure as exit 1 when tools otherwise look ok
        if failed or not eval_result.passed:
            return 1
        return 0
    except urllib.error.URLError as exc:
        _log(f"proxy unreachable at {proxy}: {exc}")
        _log("Start mcp-trace first — see README 'How to run locally'.")
        failed = True
        return 2
    except Exception as exc:  # noqa: BLE001
        _log(f"agent error: {exc}")
        failed = True
        return 2
    finally:
        if emit_turn_span:
            _export_turn_span(
                otlp_http=otlp_http,
                service_name=service_name,
                trace_id=trace_id,
                span_id=turn_span_id,
                start_ns=start_ns,
                end_ns=time.time_ns(),
                fail_faq=fail_faq,
                failed=failed,
                eval_result=eval_result,
            )



def main() -> None:
    parser = argparse.ArgumentParser(description="Toy multi-tool agent for agent-obs-lab")
    parser.add_argument(
        "--proxy",
        default="http://localhost:8001",
        help="mcp-trace base URL (default: http://localhost:8001)",
    )
    parser.add_argument(
        "--fail-faq",
        action="store_true",
        help="Call lookup_faq with an unknown topic to produce a failed span",
    )
    parser.add_argument(
        "--no-turn-span",
        action="store_true",
        help="Do not emit agent.turn parent span / traceparent (legacy sibling roots)",
    )
    parser.add_argument(
        "--otlp-http",
        default=os.environ.get("OTEL_EXPORTER_OTLP_HTTP_ENDPOINT", "http://localhost:4318"),
        help="OTLP/HTTP base for the turn parent span (default: http://localhost:4318)",
    )
    parser.add_argument(
        "--service-name",
        default=os.environ.get("MCP_TRACE_SERVICE_NAME", "agent-obs-lab"),
        help="service.name on the turn parent span",
    )
    parser.add_argument(
        "--no-eval-artifact",
        action="store_true",
        help="Do not write artifacts/eval-result.json after the turn",
    )
    parser.add_argument(
        "--eval-artifact",
        default=None,
        help="Path for eval JSON (default: artifacts/eval-result.json)",
    )
    args = parser.parse_args()
    scheme = urlparse(args.proxy).scheme
    if scheme not in ("http", "https"):
        _log(f"unsupported proxy scheme: {scheme}")
        sys.exit(2)
    art = Path(args.eval_artifact) if args.eval_artifact else None
    sys.exit(
        run_turn(
            args.proxy,
            fail_faq=args.fail_faq,
            emit_turn_span=not args.no_turn_span,
            otlp_http=args.otlp_http,
            service_name=args.service_name,
            write_artifact=not args.no_eval_artifact,
            artifact_path=art,
        )
    )


if __name__ == "__main__":
    main()
