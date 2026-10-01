#!/usr/bin/env python3
"""Toy multi-tool agent for agent-obs-lab.

Deterministic (no LLM key required): plans a short query, then issues ≥2 MCP
tools/call requests through mcp-trace.

mcp-trace --stdio exposes **Streamable HTTP** on POST / (not legacy SSE).
The agent speaks that transport so every tools/call becomes an OTel span.

Usage:
  python lab/agent.py                  # talk to http://localhost:8001
  python lab/agent.py --proxy URL
  python lab/agent.py --fail-faq       # force a failed tool turn for eval demos
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _post_rpc(
    url: str, payload: dict[str, Any], session_id: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """POST one JSON-RPC message. Returns (body_json_or_None, session_id)."""
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
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


class McpStreamableClient:
    """Minimal MCP client for Streamable HTTP (mcp-trace --stdio front door)."""

    def __init__(self, proxy: str) -> None:
        self.base = proxy.rstrip("/")
        self.url = self.base + "/"
        self.session_id: str | None = None
        self._next_id = 1

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
        )

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        req_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        _log(f"→ {method} {json.dumps(params)[:120]}")
        body, self.session_id = _post_rpc(self.url, payload, self.session_id)
        if body is not None:
            _log(f"← {json.dumps(body)[:200]}")
        return body

    def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        return self.call("tools/call", {"name": name, "arguments": arguments})


def run_turn(proxy: str, fail_faq: bool = False) -> int:
    """Run one multi-tool agent turn. Returns process exit code."""
    client = McpStreamableClient(proxy)
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

        results: list[tuple[str, dict[str, Any] | None]] = []
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
        return 1 if failed else 0
    except urllib.error.URLError as exc:
        _log(f"proxy unreachable at {proxy}: {exc}")
        _log("Start mcp-trace first — see README 'How to run locally'.")
        return 2
    except Exception as exc:  # noqa: BLE001
        _log(f"agent error: {exc}")
        return 2


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
    args = parser.parse_args()
    scheme = urlparse(args.proxy).scheme
    if scheme not in ("http", "https"):
        _log(f"unsupported proxy scheme: {scheme}")
        sys.exit(2)
    sys.exit(run_turn(args.proxy, fail_faq=args.fail_faq))


if __name__ == "__main__":
    main()
