#!/usr/bin/env python3
"""Minimal stdio MCP server with ≥2 tools for the agent-obs-lab.

Speaks just enough of the MCP JSON-RPC surface for mcp-trace to wrap it:
initialize, tools/list, tools/call, ping. No third-party deps.
"""

from __future__ import annotations

import json
import math
import sys
import time
from typing import Any

SERVER_NAME = "agent-obs-lab-toy"
SERVER_VERSION = "0.1.0"

TOOLS = [
    {
        "name": "get_weather",
        "description": "Return a canned weather report for a city (toy data).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate a tiny arithmetic expression (numbers, + - * /, parentheses).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression, e.g. '(18 + 4) * 2'",
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "lookup_faq",
        "description": "Look up a canned FAQ answer. Fails for unknown topics (for eval demos).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "FAQ topic key"},
            },
            "required": ["topic"],
        },
    },
]

WEATHER = {
    "tel aviv": "28°C, clear, humidity 55%",
    "jerusalem": "24°C, partly cloudy, humidity 40%",
    "london": "14°C, light rain, humidity 78%",
    "nyc": "19°C, overcast, humidity 62%",
}

FAQ = {
    "otel": "Export OTLP gRPC to localhost:4317 (Jaeger all-in-one) or your collector.",
    "mcp-trace": "Put mcp-trace in front of any MCP server; every tools/call becomes an OTel span.",
    "jaeger": "Open http://localhost:16686 and select service mcp-trace (or agent-obs-lab).",
}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _ok_text(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _err_text(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _safe_calc(expression: str) -> float:
    """Evaluate a restricted arithmetic expression (no names, attrs, or calls)."""
    # Character allowlist + empty builtins — toy calculator only.
    allowed = set("0123456789.+-*/()eE ")
    if not set(expression) <= allowed:
        raise ValueError("expression may only contain digits and + - * / ( ) . e")
    return float(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307 — intentionally restricted


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_weather":
        city = str(arguments.get("city", "")).strip().lower()
        time.sleep(0.08)  # tiny latency for nicer traces
        report = WEATHER.get(city)
        if not report:
            return _err_text(f"unknown city: {city!r}. try: {', '.join(WEATHER)}")
        return _ok_text(f"Weather in {city.title()}: {report}")

    if name == "calculate":
        expr = str(arguments.get("expression", "")).strip()
        time.sleep(0.05)
        try:
            value = _safe_calc(expr)
        except Exception as exc:  # noqa: BLE001 — surface as tool error
            return _err_text(f"calculate failed: {exc}")
        if not math.isfinite(value):
            return _err_text("result is not finite")
        return _ok_text(f"{expr} = {value}")

    if name == "lookup_faq":
        topic = str(arguments.get("topic", "")).strip().lower()
        time.sleep(0.12)
        answer = FAQ.get(topic)
        if not answer:
            return _err_text(
                f"no FAQ for topic={topic!r}. known: {', '.join(sorted(FAQ))}"
            )
        return _ok_text(answer)

    return _err_text(f"unknown tool: {name}")


def handle(req: dict[str, Any]) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    # Notifications have no id — acknowledge on stderr only.
    if req_id is None:
        _log(f"notification: {method}")
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        result = call_tool(name, arguments)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    _log(f"{SERVER_NAME} {SERVER_VERSION} ready (stdio)")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _log(f"bad json: {exc}")
            continue
        resp = handle(req)
        if resp is not None:
            print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()
