"""First-run dogfood: trace skip is not a failure; run-local reuses Jaeger."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from lab.agent import _export_turn_span
from lab.eval import evaluate_turn

ROOT = Path(__file__).resolve().parent.parent
RUN_LOCAL = ROOT / "scripts" / "run-local.sh"


def _ok(text: str) -> dict:
    return {"result": {"content": [{"type": "text", "text": text}]}}


def test_traces_skipped_when_nothing_listening(capsys):
    ev = evaluate_turn(
        [
            ("get_weather", _ok("ok")),
            ("calculate", _ok("ok")),
            ("lookup_faq", _ok("answer")),
        ]
    )
    _export_turn_span(
        otlp_http="http://127.0.0.1:9",
        service_name="agent-obs-lab",
        trace_id="ab" * 16,
        span_id="cd" * 8,
        start_ns=1,
        end_ns=2,
        fail_faq=False,
        failed=False,
        eval_result=ev,
    )
    err = capsys.readouterr().err
    assert "traces skipped" in err
    assert "Not a hard failure" in err
    assert "Connection refused" not in err
    assert "eval artifact is still written" in err


def test_pick_reusable_publisher_prefers_running_jaeger():
    script = """
set -euo pipefail
source "$1"
printf '%s\n' \
  'agent-obs-lab-jaeger\tCreated\t' \
  'agent-obs-lab-jaeger-1\tUp 2 minutes\t0.0.0.0:4317->4317/tcp, 0.0.0.0:4318->4318/tcp' \
  'other\trunning\t4317->4317/tcp' \
  | pick_reusable_publisher
"""
    out = subprocess.check_output(
        ["bash", "-c", script, "bash", str(RUN_LOCAL)],
        text=True,
    )
    assert out.strip() == "agent-obs-lab-jaeger-1"


def test_missing_docker_hint_names_client_and_docker_host(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "cat").symlink_to("/bin/cat")
    script = r"""
set -euo pipefail
source "$1"
export HOME="$2"
export PATH="$3"
export AGENT_OBS_SKIP_DOCKER_DISCOVERY=1
export AGENT_OBS_DOCKER_TCP_REACHABLE=0
unset DOCKER_HOST
ensure_docker
"""
    proc = subprocess.run(
        ["bash", "-c", script, "bash", str(RUN_LOCAL), str(tmp_path), str(bin_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stderr
    assert "DOCKER_HOST=tcp://127.0.0.1:2375" in proc.stderr
    assert "Docker client" in proc.stderr or "docker CLI" in proc.stderr
    assert "Install a Docker client" in proc.stderr


def test_tcp_daemon_without_cli_uses_api_instead_of_hard_fail(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = r"""
set -euo pipefail
source "$1"
export HOME="$2"
export PATH="$3"
export AGENT_OBS_SKIP_DOCKER_DISCOVERY=1
export AGENT_OBS_DOCKER_TCP_REACHABLE=1
unset DOCKER_HOST
ensure_docker
printf 'api=%s host=%s\n' "$AGENT_OBS_DOCKER_API" "$DOCKER_HOST"
"""
    proc = subprocess.run(
        ["bash", "-c", script, "bash", str(RUN_LOCAL), str(tmp_path), str(bin_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "api=1" in proc.stdout
    assert "host=tcp://127.0.0.1:2375" in proc.stdout
    assert "Using the Docker HTTP API" in proc.stderr


def test_proxy_default_honors_mcp_trace_port(monkeypatch):
    """Omitted --proxy follows MCP_TRACE_PORT, not a hardcoded :8001."""
    monkeypatch.setenv("MCP_TRACE_PORT", "8123")
    seen: dict[str, str] = {}

    def fake_run(proxy, **kwargs):
        seen["proxy"] = proxy
        return 0

    monkeypatch.setattr("lab.agent.run_turn", fake_run)
    monkeypatch.setattr(sys, "argv", ["agent.py"])
    from lab.agent import main

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert seen["proxy"] == "http://localhost:8123"


def test_explicit_proxy_overrides_mcp_trace_port(monkeypatch):
    monkeypatch.setenv("MCP_TRACE_PORT", "8123")
    seen: dict[str, str] = {}

    def fake_run(proxy, **kwargs):
        seen["proxy"] = proxy
        return 0

    monkeypatch.setattr("lab.agent.run_turn", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["agent.py", "--proxy", "http://127.0.0.1:9000"]
    )
    from lab.agent import main

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert seen["proxy"] == "http://127.0.0.1:9000"


def test_run_trace_refuses_busy_port(tmp_path: Path):
    """Preflight exits before mcp-trace can log listening + bind failure."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ran = tmp_path / "ran"
    fake = bin_dir / "mcp-trace"
    fake.write_text(f"#!/bin/sh\necho ran > {ran}\nexit 0\n")
    fake.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["MCP_TRACE_PORT"] = str(port)
    env.pop("GOPATH", None)
    try:
        proc = subprocess.run(
            [str(ROOT / "scripts" / "run-trace.sh")],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        sock.close()
    assert proc.returncode == 1, proc.stderr
    assert "already in use" in proc.stderr
    assert "bind: address already in use" in proc.stderr
    assert not ran.exists()


def test_readme_client_matches_run_trace_default():
    readme = (ROOT / "README.md").read_text()
    script = (ROOT / "scripts" / "run-trace.sh").read_text()
    printed = "python3 lab/agent.py --proxy http://localhost:${PORT}"
    assert printed in script
    assert "python3 lab/agent.py --proxy http://localhost:8001" in readme


def test_default_jaeger_names_include_compose_and_exact():
    """Reuse accepts agent-obs-lab-jaeger-1; fan-out teardown must too."""
    script = r"""
set -euo pipefail
source "$1"
printf '%s\n' \
  $'agent-obs-lab-jaeger-1\tUp 13 hours\t0.0.0.0:16686->16686/tcp' \
  $'agent-obs-lab-jaeger\tExited\t' \
  $'agent-obs-lab-dogfood-jaeger-1\tUp\t0.0.0.0:16686->16686/tcp' \
  $'agent-obs-lab-dogfood-phoenix-1\tUp\t6006->6006/tcp' \
  $'agent-obs-lab-dogfood-otel-collector-1\tUp\t4317->4317/tcp' \
  $'unrelated-jaeger-1\tUp\t0.0.0.0:16686->16686/tcp' \
  $'other\trunning\t4317->4317/tcp' \
  | names_of_default_jaegers
"""
    out = subprocess.check_output(
        ["bash", "-c", script, "bash", str(RUN_LOCAL)],
        text=True,
    )
    assert set(out.split()) == {
        "agent-obs-lab-jaeger-1",
        "agent-obs-lab-jaeger",
        "agent-obs-lab-dogfood-jaeger-1",
    }


def test_fanout_stop_removes_reused_jaeger_names(tmp_path: Path):
    """Compose down of this project is not enough; rm the reused Jaeger names."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    fake = bin_dir / "docker"
    fake.write_text(
        f"""#!/bin/sh
printf '%s\\n' "$*" >> {log}
if [ "$1" = ps ]; then
  printf '%s\\t%s\\t%s\\n' \\
    'agent-obs-lab-jaeger-1' 'Up 13 hours' '0.0.0.0:16686->16686/tcp, 0.0.0.0:4317->4317/tcp' \\
    'agent-obs-lab-jaeger' 'Exited' '' \\
    'agent-obs-lab-dogfood-jaeger-1' 'Up' '0.0.0.0:16686->16686/tcp' \\
    'agent-obs-lab-dogfood-phoenix-1' 'Up' '0.0.0.0:6006->6006/tcp' \\
    'agent-obs-lab-dogfood-otel-collector-1' 'Up' '0.0.0.0:4317->4317/tcp' \\
    'unrelated-jaeger-1' 'Up' '0.0.0.0:16686->16686/tcp' \\
    'other' 'running' '4317->4317/tcp'
  exit 0
fi
exit 0
"""
    )
    fake.chmod(0o755)
    script = r"""
set -euo pipefail
source "$1"
export PATH="$2:/usr/bin:/bin"
export AGENT_OBS_DOCKER_API=0
unset DOCKER_HOST
command -v docker
stop_default_backends
"""
    proc = subprocess.run(
        ["bash", "-c", script, "bash", str(RUN_LOCAL), str(bin_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("/docker")
    assert str(bin_dir) in proc.stdout
    logged = log.read_text()
    for name in (
        "agent-obs-lab-jaeger-1",
        "agent-obs-lab-jaeger",
        "agent-obs-lab-dogfood-jaeger-1",
    ):
        assert f"rm -f {name}" in logged
    for name in (
        "agent-obs-lab-dogfood-phoenix-1",
        "agent-obs-lab-dogfood-otel-collector-1",
        "unrelated-jaeger-1",
        "other",
    ):
        assert f"rm -f {name}" not in logged
    assert "compose -f docker-compose.yml down" in logged


def test_default_path_reuses_jaeger_without_removing_it(tmp_path: Path):
    """No --fanout: a live compose Jaeger is reused, not rm'd."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    fake = bin_dir / "docker"
    fake.write_text(
        f"""#!/bin/sh
printf '%s\\n' "$*" >> {log}
if [ "$1" = ps ]; then
  printf '%s\\t%s\\t%s\\n' \\
    'agent-obs-lab-jaeger-1' 'Up 2 minutes' '0.0.0.0:4317->4317/tcp, 0.0.0.0:16686->16686/tcp'
  exit 0
fi
exit 0
"""
    )
    fake.chmod(0o755)
    script = r"""
set -euo pipefail
source "$1"
export PATH="$2:/usr/bin:/bin"
export AGENT_OBS_DOCKER_API=0
unset DOCKER_HOST
start_default_backend
"""
    proc = subprocess.run(
        ["bash", "-c", script, "bash", str(RUN_LOCAL), str(bin_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "reusing running container agent-obs-lab-jaeger-1" in proc.stdout
    logged = log.read_text()
    assert "rm -f" not in logged
    assert "down" not in logged
