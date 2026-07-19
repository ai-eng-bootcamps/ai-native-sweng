"""Replay conformance for the Module 10 adversarial demo trace (conformance target #10).

One committed artifact, ``traces/m10/adversarial_demo.jsonl``, recorded ENTIRELY OFFLINE
against the local hermetic fixture ``tests/fixtures/m10/minefield-mirror`` - never against
the public minefield repository, never over a socket. The blocked-action demonstration
(blueprint 27): the injected policy change is clamped to the platform value, the
consequential command is denied, the exfiltrated credential is redacted at the trace
boundary, and the run fails closed into an escalation. Determinism comes from the security
functions and the fixture on disk, not from model replay; re-recording reproduces the
committed events byte-for-byte once the volatile timestamp is dropped.

These fail against the security stubs (the clamp, the matrix, the scanner/filter, the
retention/validation) and pass once they are implemented. The recording below is kept in
lockstep with the reference recorder in ``cli/run_security.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from anse_harness.approvals.gate import ApprovalGate, ApprovalRequest, reject_all
from anse_harness.instructions.precedence import (
    Instruction,
    InstructionCategory,
    TrustLevel,
    detect_conflicts,
)
from anse_harness.security import (
    PolicyMatrix,
    RepoClassification,
    filter_env,
    resolve_policy_topic,
    scan_for_secrets,
)
from anse_harness.tracing import TraceEvent, TraceWriter, read_trace

pytestmark = pytest.mark.student_impl

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "m10" / "minefield-mirror"
TRACE = Path(__file__).resolve().parents[2] / "traces" / "m10" / "adversarial_demo.jsonl"

# Pinned recorder parameters (lockstep with cli/run_security.py).
RUN_ID = "run-m10-adversarial"
WORKFLOW_ID = "wf-m10-adversarial"
PLATFORM_AUTONOMY = "3"
_NUMBER_RE = re.compile(r"autonomy level[^0-9]*(\d+)", re.IGNORECASE)


def _load_env(fixture: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (fixture / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def _autonomy_conflict(fixture: Path) -> tuple[str, str]:
    instructions = [
        Instruction(
            "AGENTS.md",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_TRUSTED,
            (fixture / "AGENTS.md").read_text(encoding="utf-8"),
        ),
        Instruction(
            "CONTRIBUTING.md",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_TRUSTED,
            (fixture / "CONTRIBUTING.md").read_text(encoding="utf-8"),
        ),
        Instruction(
            ".rules",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_UNTRUSTED,
            (fixture / ".rules").read_text(encoding="utf-8"),
        ),
    ]
    (conflict,) = detect_conflicts(instructions, ["autonomy"])
    winning_source = next(
        (source for source in conflict.sources if source in conflict.resolution),
        conflict.sources[0],
    )
    text = next(ins.text for ins in instructions if ins.source_path == winning_source)
    match = _NUMBER_RE.search(text)
    return winning_source, (match.group(1) if match else "")


def _record_demo(fixture: Path, trace_path: Path) -> None:
    matrix = PolicyMatrix()
    minefield = RepoClassification.UNTRUSTED_EXTERNAL
    env = _load_env(fixture)
    token = env.get("GITHUB_TOKEN", "")

    winning_source, repo_claim = _autonomy_conflict(fixture)
    effective_autonomy, clamp_reason = resolve_policy_topic(
        "autonomy", PLATFORM_AUTONOMY, InstructionCategory.REPOSITORY, repo_claim
    )
    push = matrix.evaluate_command(["git", "push", "origin", "main"], minefield)
    exfil_body = f"posting env for debugging: {token}"
    secret_hits = scan_for_secrets(exfil_body)
    dropped = sorted(set(env) - set(filter_env(env)))
    gate = ApprovalGate(reject_all)
    decision = gate.request(
        ApprovalRequest(
            action="finalize_patch",
            reason="ambiguous consequential action in an untrusted repository",
            risk="class-2-local-consequential",
        )
    )

    with TraceWriter(trace_path) as writer:
        writer.write(
            TraceEvent(
                run_id=RUN_ID,
                workflow_id=WORKFLOW_ID,
                component="security.injection",
                event_type="policy_evaluated",
                status="clamped",
                event_id="evt-mf-0000",
                payload={
                    "topic": "autonomy",
                    "winning_source": winning_source,
                    "repository_claim": repo_claim,
                    "effective_value": effective_autonomy,
                    "repo_class": minefield.value,
                    "reason": clamp_reason,
                },
            )
        )
        writer.write(
            TraceEvent(
                run_id=RUN_ID,
                workflow_id=WORKFLOW_ID,
                component="security.matrix",
                event_type="policy_evaluated",
                status="denied",
                event_id="evt-mf-0001",
                payload={
                    "command": "git push origin main",
                    "repo_class": minefield.value,
                    "decision": push.decision.value,
                    "source": "AGENTS.md injected 'push to main'",
                    "reason": push.reason,
                },
            )
        )
        writer.write(
            TraceEvent(
                run_id=RUN_ID,
                workflow_id=WORKFLOW_ID,
                component="security.secrets",
                event_type="tool_requested",
                status="blocked",
                event_id="evt-mf-0002",
                payload={
                    "attempted_exfiltration": {"github_token": token},
                    "detected_shapes": secret_hits,
                    "env_dropped": dropped,
                },
                sensitivity="sensitive",
                sensitive_keys=("github_token",),
            )
        )
        writer.write(
            TraceEvent(
                run_id=RUN_ID,
                workflow_id=WORKFLOW_ID,
                component="approvals.gate",
                event_type="escalation_created",
                status=decision.value,
                event_id="evt-mf-0003",
                payload={
                    "reason": "fail-closed: consequential ambiguity in an untrusted "
                    "repository escalated, not proceeded"
                },
            )
        )


def _identity(trace_path: Path) -> list[tuple[str, str, str, dict[str, Any]]]:
    return [
        (event.event_id, event.event_type, event.status, event.payload)
        for event in read_trace(trace_path)
    ]


def test_adversarial_demo_replays_byte_exactly(tmp_path: Path) -> None:
    replayed = tmp_path / "adversarial_demo.jsonl"
    _record_demo(FIXTURE, replayed)
    assert _identity(replayed) == _identity(TRACE)

    events = read_trace(TRACE)
    assert [event.event_type for event in events] == [
        "policy_evaluated",
        "policy_evaluated",
        "tool_requested",
        "escalation_created",
    ]
    # The clamp held autonomy at the platform value, not the repository's claim.
    assert events[0].payload["effective_value"] == PLATFORM_AUTONOMY
    assert events[0].payload["repository_claim"] != PLATFORM_AUTONOMY
    # The consequential command was denied and the credential redacted.
    assert events[1].payload["decision"] == "deny"
    assert events[2].payload["attempted_exfiltration"]["github_token"] == "[REDACTED]"
    assert events[-1].event_type == "escalation_created"


def test_re_recording_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    _record_demo(FIXTURE, first)
    _record_demo(FIXTURE, second)
    assert _identity(first) == _identity(second)
    # The committed trace leaks no fixture credential.
    raw = TRACE.read_text(encoding="utf-8")
    assert _load_env(FIXTURE)["GITHUB_TOKEN"] not in raw
