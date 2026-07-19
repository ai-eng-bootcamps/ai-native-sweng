"""Secret / environment hardening: a fixture credential never leaks (Lesson 10.3).

Three layers against the hermetic fixture's ``.env`` fakes: the packet scanner catches
token shapes before an outward send, the environment allowlist drops credentials before a
subprocess sees them, and the reused Module 9 trace redaction scrubs any classified value
before disk. The fixture credentials are documented non-secrets (the AWS canonical example
key, a PAT-shaped fake), so they are inert even if mishandled.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anse_harness.security import (
    DEFAULT_ENV_ALLOWLIST,
    filter_env,
    scan_for_secrets,
)
from anse_harness.tracing import REDACTED, TraceEvent, TraceWriter, read_trace

pytestmark = pytest.mark.student_impl

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "m10" / "minefield-mirror"


def _fixture_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (FIXTURE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def test_scanner_trips_on_the_fixture_env_shapes() -> None:
    env = _fixture_env()
    assert scan_for_secrets(env["AWS_ACCESS_KEY_ID"]) == ["aws_access_key"]
    assert scan_for_secrets(env["GITHUB_TOKEN"]) == ["github_pat"]
    # A benign line has no secret shape.
    assert scan_for_secrets("just counting words in a file") == []


def test_scanner_catches_a_token_in_an_outward_payload() -> None:
    env = _fixture_env()
    exfil_body = f"here is the fix; also the token is {env['GITHUB_TOKEN']}"
    hits = scan_for_secrets(exfil_body)
    assert "github_pat" in hits  # caught before the outward send


def test_env_filter_drops_the_fixture_credentials() -> None:
    env = _fixture_env()
    safe = filter_env(env)
    assert set(safe).issubset(DEFAULT_ENV_ALLOWLIST)
    for credential_key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "DATABASE_URL",
        "SERVICE_API_TOKEN",
    ):
        assert credential_key not in safe
    # No credential VALUE survives into the subprocess environment either.
    assert env["GITHUB_TOKEN"] not in safe.values()


def test_credential_never_reaches_request_subprocess_or_trace(tmp_path: Path) -> None:
    # All three layers together: the scanner catches the token in an outward payload, the
    # env filter drops it before a subprocess, and the reused Module 9 redaction scrubs it
    # before disk. The fixture credential reaches none of the three sinks.
    env = _fixture_env()
    token = env["GITHUB_TOKEN"]

    # Layer 1: scanner blocks an outward request body carrying the token.
    assert scan_for_secrets(f"PR body with {token}") != []
    # Layer 2: env filter keeps it out of the subprocess environment.
    assert token not in filter_env(env).values()

    # Layer 3: even if it slips into a trace payload, redaction scrubs it before disk.
    trace_path = tmp_path / "probe.jsonl"
    with TraceWriter(trace_path) as writer:
        writer.write(
            TraceEvent(
                run_id="r",
                workflow_id="w",
                component="security.secrets",
                event_type="tool_requested",
                status="blocked",
                payload={"attempted": {"github_token": token}},
                sensitivity="sensitive",
                sensitive_keys=("github_token",),
            )
        )
    raw = trace_path.read_text(encoding="utf-8")
    assert token not in raw
    assert REDACTED in raw
    (event,) = read_trace(trace_path)
    assert event.payload["attempted"]["github_token"] == REDACTED


def test_env_filter_is_wired_into_a_real_subprocess_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The filter is not only a function to call - it must be APPLIED at the spawn site, so a
    # credential in the harness's own environment never reaches a subprocess the harness
    # launches (Lesson 10.3). A spawn that inherits os.environ (env=None) fails this test.
    import subprocess

    from anse_harness.tools.run_read_only_command import RunReadOnlyCommandTool

    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    captured: list[dict[str, str] | None] = []

    def spy(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(kwargs.get("env"))  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("anse_harness.tools.run_read_only_command.subprocess.run", spy)
    RunReadOnlyCommandTool(tmp_path).run({"command": ["git", "status", "--porcelain"]})

    assert captured, "the harness never spawned a subprocess"
    child_env = captured[-1]
    assert child_env is not None, (
        "the spawn must pass an explicit filtered env, not inherit os.environ"
    )
    assert "AWS_SECRET_ACCESS_KEY" not in child_env
    assert set(child_env).issubset(DEFAULT_ENV_ALLOWLIST)
