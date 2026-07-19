"""Replay conformance for the Module 9 integration traces (conformance target #9).

Two committed artifacts under ``traces/m09``, both recorded against the LOCAL
DOUBLE and the LOCAL MCP server - never against GitHub, never over a socket:

* ``integration_run.jsonl`` - issue intake, CI read, and an approved draft-PR
  request through ``GitHubAdapter`` over ``LocalGitHubDouble``.
* ``mcp_session.jsonl`` - one policy-gated ``repo_search`` MCP tool call through
  the hand-rolled stdio client against ``anse_harness.tools.mcp_repo_server``.

Determinism here comes from the double and the local server, not from model
replay - the replay machinery never touches a tool or a socket. Re-recording the
same offline flow reproduces the committed events byte-for-byte once the volatile
timestamp is dropped. These fail against the scaffolding stubs (the adapter and
client methods, and Modules 3 and 7) and pass once they are implemented.

The pinned parameters below must stay in lockstep with the reference recorder in
``cli/run_integration.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.integrations import (
    ExternalActionAudit,
    GitHubAdapter,
    IntegrationRecorder,
    LocalGitHubDouble,
    MCPToolCapability,
    StdioMCPClient,
    gated_tools_call,
)
from anse_harness.tracing import TraceEvent, TraceWriter, read_trace

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m09"
TRACES = Path(__file__).resolve().parents[2] / "traces" / "m09"

# Pinned recorder parameters (lockstep with cli/run_integration.py).
PLACEHOLDER_TOKEN = "ghp_OFFLINE_PLACEHOLDER_never_on_the_wire_000000000"
INTEGRATION_RUN_ID = "run-m09-integration"
INTEGRATION_WORKFLOW_ID = "wf-m09-integration"
MCP_RUN_ID = "run-m09-mcp"
MCP_WORKFLOW_ID = "wf-m09-mcp"
TASK_ID = "bp-integration"
ARTIFACT_VERSION = "v0001"
ISSUE_NUMBER = 7
CI_REF = "feature/healthz"
PR_TITLE = "Add a /healthz readiness endpoint"
PR_HEAD = "feature/healthz"
PR_BASE = "main"
PR_DIFF = (
    "--- a/internal/health/health.go\n"
    "+++ b/internal/health/health.go\n"
    "@@\n"
    "+// Healthz reports readiness.\n"
)
REPO_SEARCH_QUERY = "Normalize"
SERVER_COMMAND = [sys.executable, "-m", "anse_harness.tools.mcp_repo_server"]


def _identity(trace_path: Path) -> list[tuple[str, str, str, dict[str, Any]]]:
    """The replay-relevant identity of a trace: (event_id, type, status, payload)."""
    return [
        (event.event_id, event.event_type, event.status, event.payload)
        for event in read_trace(trace_path)
    ]


def _record_integration_run(trace_path: Path) -> None:
    double = LocalGitHubDouble.from_fixtures(FIXTURES)
    with TraceWriter(trace_path) as writer:
        adapter = GitHubAdapter(
            double,
            PLACEHOLDER_TOKEN,
            ApprovalGate(approve_all),
            run_id=INTEGRATION_RUN_ID,
            workflow_id=INTEGRATION_WORKFLOW_ID,
            tracer=writer,
        )
        adapter.read_issue(ISSUE_NUMBER)
        adapter.read_ci_status(CI_REF)
        adapter.create_draft_pr(
            task_id=TASK_ID,
            workflow_id=INTEGRATION_WORKFLOW_ID,
            artifact_version=ARTIFACT_VERSION,
            title=PR_TITLE,
            head=PR_HEAD,
            base=PR_BASE,
            diff=PR_DIFF,
        )


def _record_mcp_session(trace_path: Path) -> None:
    client = StdioMCPClient(SERVER_COMMAND)
    try:
        client.initialize()
        client.tools_list()
        with TraceWriter(trace_path) as writer:
            recorder = IntegrationRecorder(writer, MCP_RUN_ID, MCP_WORKFLOW_ID)
            gated_tools_call(
                client,
                MCPToolCapability("repo_search", side_effect_class=0),
                {"query": REPO_SEARCH_QUERY},
                gate=ApprovalGate(approve_all),
                recorder=recorder,
            )
    finally:
        client.close()


def test_integration_run_replays_byte_exactly(tmp_path: Path) -> None:
    replayed = tmp_path / "integration_run.jsonl"
    _record_integration_run(replayed)
    assert _identity(replayed) == _identity(TRACES / "integration_run.jsonl")

    events = read_trace(TRACES / "integration_run.jsonl")
    types = [event.event_type for event in events]
    assert types == [
        "tool_requested",
        "tool_completed",
        "tool_requested",
        "tool_completed",
        "approval_requested",
        "approval_resolved",
        "tool_requested",
        "tool_completed",
        "artifact_created",
    ]
    completed = next(
        event
        for event in events
        if event.event_type == "tool_completed" and event.payload.get("action") == "create_draft_pr"
    )
    assert completed.payload["draft"] is True
    assert completed.payload["deduped"] is False
    assert completed.payload["pr"] == 101

    audit = ExternalActionAudit.from_payload(
        next(event.payload for event in events if event.event_type == "artifact_created")
    )
    assert audit.approved is True
    assert audit.outcome == "completed"
    assert audit.status == 201
    assert audit.idempotency_key is not None and audit.idempotency_key.startswith("idem-")


def test_mcp_session_replays_byte_exactly(tmp_path: Path) -> None:
    replayed = tmp_path / "mcp_session.jsonl"
    _record_mcp_session(replayed)
    assert _identity(replayed) == _identity(TRACES / "mcp_session.jsonl")

    types = [event.event_type for event in read_trace(TRACES / "mcp_session.jsonl")]
    assert types == ["policy_evaluated", "tool_requested", "tool_completed"]


def _volatile_free(event: TraceEvent) -> dict[str, Any]:
    data = event.to_dict()
    data.pop("timestamp")
    return data


def test_re_recording_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    _record_integration_run(first)
    _record_integration_run(second)
    assert [_volatile_free(event) for event in read_trace(first)] == [
        _volatile_free(event) for event in read_trace(second)
    ]
