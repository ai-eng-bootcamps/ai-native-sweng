"""Student-implemented tests for the Module 9 GitHub adapter (against the double).

Every required validation from spec §16 lives here, exercised offline through the
local double: credential scoping, idempotent create, duplicate-PR prevention,
timeout handling, cancellation, draft-only behaviour, audit-record completeness,
and external actions appearing in traces. These fail against the scaffolding
stubs and pass once the adapter (and Modules 3 and 7) are implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all, reject_all
from anse_harness.integrations import (
    ExternalActionAudit,
    GitHubAdapter,
    IntegrationCancelledError,
    IntegrationError,
    LocalGitHubDouble,
    draft_pr_from_workflow_result,
)
from anse_harness.tracing import TraceWriter, read_trace

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m09"

TOKEN = "ghp_TESTSECRET_must_never_appear_in_a_trace_0123456789"


def _double() -> LocalGitHubDouble:
    return LocalGitHubDouble.from_fixtures(FIXTURES)


def _adapter(
    double: LocalGitHubDouble, resolver: Any = approve_all, writer: TraceWriter | None = None
) -> GitHubAdapter:
    return GitHubAdapter(
        double,
        TOKEN,
        ApprovalGate(resolver),
        run_id="run-test",
        workflow_id="wf-test",
        tracer=writer,
    )


_CREATE_KW: dict[str, Any] = {
    "task_id": "bp-integration",
    "workflow_id": "wf-test",
    "artifact_version": "v0001",
    "title": "Add a /healthz readiness endpoint",
    "head": "feature/healthz",
    "base": "main",
    "diff": "--- a/x\n+++ b/x\n",
}


def test_read_issue_and_ci_need_no_approval() -> None:
    double = _double()
    adapter = _adapter(double, resolver=reject_all)  # reads never touch the gate
    assert adapter.read_issue(7)["title"] == "Add a /healthz readiness endpoint"
    assert adapter.read_ci_status("feature/healthz")["state"] == "success"


def test_full_flow_creates_one_draft_pr_and_traces_it(tmp_path: Path) -> None:
    double = _double()
    trace = tmp_path / "run.jsonl"
    with TraceWriter(trace) as writer:
        adapter = _adapter(double, writer=writer)
        adapter.read_issue(7)
        adapter.read_ci_status("feature/healthz")
        result = adapter.create_draft_pr(**_CREATE_KW)
    assert result["draft"] is True
    assert result["deduped"] is False
    types = [event.event_type for event in read_trace(trace)]
    assert types.count("tool_requested") >= 3
    assert types.count("tool_completed") >= 3
    assert "approval_requested" in types and "approval_resolved" in types
    assert "artifact_created" in types  # the external-action audit record


def test_create_is_idempotent_and_prevents_duplicates() -> None:
    double = _double()
    adapter = _adapter(double)
    first = adapter.create_draft_pr(**_CREATE_KW)
    second = adapter.create_draft_pr(**_CREATE_KW)
    assert first["number"] == second["number"]
    assert second["deduped"] is True
    assert len(double.created_prs) == 1


def test_draft_flag_is_hard_coded_true() -> None:
    double = _double()
    adapter = _adapter(double)
    adapter.create_draft_pr(**_CREATE_KW)
    sent = [request for request in double.sent if request.action == "create_draft_pr"]
    assert sent and sent[0].body["draft"] is True


def test_idempotency_marker_in_pr_body() -> None:
    double = _double()
    adapter = _adapter(double)
    adapter.create_draft_pr(**_CREATE_KW)
    sent = next(request for request in double.sent if request.action == "create_draft_pr")
    assert sent.idempotency_key is not None
    assert f"<!-- idem:{sent.idempotency_key} -->" in sent.body["body"]


def test_timeout_raises_retryable_integration_error() -> None:
    double = _double()
    double.raise_timeout = True
    adapter = _adapter(double)
    with pytest.raises(IntegrationError) as excinfo:
        adapter.read_issue(7)
    assert excinfo.value.retryable is True


def test_cancellation_creates_no_pr_and_never_reaches_transport() -> None:
    double = _double()
    adapter = _adapter(double)
    with pytest.raises(IntegrationCancelledError):
        adapter.create_draft_pr(cancel=True, **_CREATE_KW)
    assert double.created_prs == {}
    assert not any(request.action == "create_draft_pr" for request in double.sent)


def test_rejected_approval_blocks_the_create(tmp_path: Path) -> None:
    double = _double()
    trace = tmp_path / "reject.jsonl"
    with TraceWriter(trace) as writer:
        adapter = _adapter(double, resolver=reject_all, writer=writer)
        with pytest.raises(IntegrationError) as excinfo:
            adapter.create_draft_pr(**_CREATE_KW)
    assert excinfo.value.retryable is False
    assert double.created_prs == {}
    assert not any(request.action == "create_draft_pr" for request in double.sent)
    # A rejected outward action still leaves an audit record.
    audits = [
        ExternalActionAudit.from_payload(event.payload)
        for event in read_trace(trace)
        if event.event_type == "artifact_created"
    ]
    assert audits and audits[0].approved is False and audits[0].outcome == "rejected"


def test_transport_failure_on_send_still_audits_and_reraises(tmp_path: Path) -> None:
    double = _double()
    double.raise_timeout = True  # the send raises AFTER approval, at the transport
    trace = tmp_path / "failed.jsonl"
    with TraceWriter(trace) as writer:
        adapter = _adapter(double, writer=writer)
        with pytest.raises(IntegrationError) as excinfo:
            adapter.create_draft_pr(**_CREATE_KW)
    assert excinfo.value.retryable is True  # the Module 7 taxonomy survives the audit
    # An approved-but-failed send still leaves an audit record (outcome "failed"),
    # exactly as the rejected and cancelled paths do.
    audits = [
        ExternalActionAudit.from_payload(event.payload)
        for event in read_trace(trace)
        if event.event_type == "artifact_created"
    ]
    assert audits and audits[0].approved is True and audits[0].outcome == "failed"


def test_audit_record_is_complete_and_credential_free(tmp_path: Path) -> None:
    double = _double()
    trace = tmp_path / "audit.jsonl"
    with TraceWriter(trace) as writer:
        adapter = _adapter(double, writer=writer)
        adapter.create_draft_pr(**_CREATE_KW)
    audit_event = next(
        event for event in read_trace(trace) if event.event_type == "artifact_created"
    )
    audit = ExternalActionAudit.from_payload(audit_event.payload)
    assert audit.action == "create_draft_pr"
    assert audit.approved is True
    assert audit.outcome == "completed"
    assert audit.status == 201
    assert audit.idempotency_key is not None


def test_token_never_appears_in_any_trace(tmp_path: Path) -> None:
    double = _double()
    trace = tmp_path / "run.jsonl"
    with TraceWriter(trace) as writer:
        adapter = _adapter(double, writer=writer)
        adapter.read_issue(7)
        adapter.create_draft_pr(**_CREATE_KW)
    assert "TESTSECRET" not in trace.read_text(encoding="utf-8")
    assert TOKEN not in trace.read_text(encoding="utf-8")


def test_draft_pr_hook_packages_a_workflow_result() -> None:
    class _Result:
        patch = "--- a/health.go\n+++ b/health.go\n"

    double = _double()
    adapter = _adapter(double)
    result = draft_pr_from_workflow_result(
        _Result(),
        platform=adapter,
        task_id="bp-integration",
        workflow_id="wf-test",
        artifact_version="v0001",
        title="Add a /healthz readiness endpoint",
        head="feature/healthz",
        base="main",
    )
    assert result is not None
    assert result["draft"] is True
    assert len(double.created_prs) == 1
