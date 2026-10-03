"""First-run dogfood: trace skip is not a failure; run-local reuses Jaeger."""

from __future__ import annotations

import subprocess
from pathlib import Path

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
