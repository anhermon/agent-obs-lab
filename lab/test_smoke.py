"""Smoke tests for the toy MCP server (no mcp-trace / network required)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "mcp_server.py"


def _rpc(proc: subprocess.Popen, payload: dict) -> dict | None:
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    if payload.get("id") is None:
        return None
    line = proc.stdout.readline()
    assert line, "expected JSON-RPC response"
    return json.loads(line)


def test_tools_list_and_two_calls():
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        init = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert init and init["result"]["serverInfo"]["name"] == "agent-obs-lab-toy"

        listed = _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {t["name"] for t in listed["result"]["tools"]}
        assert {"get_weather", "calculate", "lookup_faq"} <= names

        weather = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_weather", "arguments": {"city": "Tel Aviv"}},
            },
        )
        text = weather["result"]["content"][0]["text"]
        assert "28°C" in text
        assert not weather["result"].get("isError")

        calc = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "calculate", "arguments": {"expression": "(18+4)*2"}},
            },
        )
        assert "= 44.0" in calc["result"]["content"][0]["text"]

        fail = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "lookup_faq", "arguments": {"topic": "missing"}},
            },
        )
        assert fail["result"].get("isError") is True
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_calculate_rejects_names():
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        bad = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "calculate", "arguments": {"expression": "__import__('os')"}},
            },
        )
        assert bad["result"].get("isError") is True
    finally:
        proc.kill()
        proc.wait(timeout=5)
