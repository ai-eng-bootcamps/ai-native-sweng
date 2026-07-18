"""Contract tests for the approval gate (Lesson 3.5: approval boundary).

The gate routes every request to its resolver, records every request/decision pair, and
rejects by default - an approval boundary that approves by default is not a boundary.
These fail against the scaffolding stubs and pass once the gate is implemented to the
reference behaviour.
"""

import pytest

from anse_harness.approvals.gate import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalRequest,
    approve_all,
)

pytestmark = pytest.mark.student_impl


def _request() -> ApprovalRequest:
    return ApprovalRequest(
        action="finalize_patch",
        reason="validated change ready to leave the sandbox",
        affected_paths=("internal/booking/holder.go",),
        risk="class-1-local-reversible",
        diff="--- a/x\n+++ b/x\n",
        validation_ok=True,
    )


def test_gate_rejects_by_default() -> None:
    gate = ApprovalGate()
    assert gate.request(_request()) is ApprovalDecision.REJECTED


def test_gate_resolves_through_its_resolver() -> None:
    gate = ApprovalGate(approve_all)
    assert gate.request(_request()) is ApprovalDecision.APPROVED


def test_gate_records_every_request_and_decision() -> None:
    gate = ApprovalGate(approve_all)
    request = _request()
    gate.request(request)
    gate.request(request)
    assert len(gate.log) == 2
    logged_request, logged_decision = gate.log[0]
    assert logged_request is request
    assert logged_decision is ApprovalDecision.APPROVED


def test_request_payload_carries_the_decision_evidence() -> None:
    # The approver acts on evidence (spec 7.14): action, reason, affected assets, risk,
    # diff, and validation status all travel in the trace payload.
    gate = ApprovalGate(approve_all)
    request = _request()
    gate.request(request)
    payload = request.to_payload()
    assert payload["action"] == "finalize_patch"
    assert payload["affected_paths"] == ["internal/booking/holder.go"]
    assert payload["risk"] == "class-1-local-reversible"
    assert payload["diff"] is not None
    assert payload["validation_ok"] is True
