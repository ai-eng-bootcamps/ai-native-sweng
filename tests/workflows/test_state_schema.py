"""The workflow state schema (canonical-reference.md section 13).

The state dataclasses and their serialization are SUPPLIED infrastructure, so these
tests run in the default suite: they pin the state payload to the canonical schema's
exact groups and keys, the payload round trip the state store relies on, and the
loud failure on schema-version drift (spec 7.10: state formats are versioned).
"""

import pytest

from anse_harness.workflows.state import (
    WORKFLOW_STATE_SCHEMA_VERSION,
    ApprovalRecord,
    FailureEvent,
    StateSchemaError,
    WorkerInvocation,
    WorkflowState,
    WorkflowStatus,
    initial_workflow_state,
)


def _state() -> WorkflowState:
    state = initial_workflow_state(
        "wf-1",
        workflow_type="feature-task",
        workflow_version="1",
        task_id="t-1",
        termination_policy="explicit terminal stage required",
        approval_policy="deny by default",
    )
    state.status.state = WorkflowStatus.RUNNING
    state.status.current_stage = "plan_approval"
    state.task.specification_artifact_id = "task-spec-t-1"
    state.artifacts.plan = "plan-t-1"
    state.artifacts.patches.append("patch-t-1-1")
    state.artifacts.validation_reports.append("validation-t-1-1")
    state.workers.invocations.append(
        WorkerInvocation(
            run_id="run-wf-1-investigate",
            worker_type="investigator",
            stage="investigate",
            status="completed",
        )
    )
    state.budgets.monetary_used = 0.0123
    state.budgets.token_used = 4200
    state.budgets.worker_count = 1
    state.approvals.resolved.append(
        ApprovalRecord(action="approve_plan", stage="plan_approval", decision="approved")
    )
    state.failures.events.append(FailureEvent(stage="validate", reason="example"))
    state.checkpoints.latest = "cp-wf-1-v0003"
    return state


def test_payload_carries_the_canonical_groups() -> None:
    payload = _state().to_payload()
    assert set(payload) == {
        "schema_version",
        "workflow_id",
        "workflow_type",
        "workflow_version",
        "task",
        "status",
        "policies",
        "artifacts",
        "workers",
        "budgets",
        "approvals",
        "failures",
        "checkpoints",
    }
    assert payload["schema_version"] == WORKFLOW_STATE_SCHEMA_VERSION
    assert set(payload["artifacts"]) == {
        "plan",
        "patches",
        "validation_reports",
        "review_findings",
        "consolidated_review",
        "pull_request",
    }
    assert set(payload["budgets"]) == {
        "monetary_used",
        "token_used",
        "elapsed_seconds",
        "worker_count",
        "retry_count",
    }
    assert payload["status"] == {
        "state": "running",
        "current_stage": "plan_approval",
        "termination_reason": None,
    }


def test_payload_round_trip_preserves_the_state() -> None:
    state = _state()
    rebuilt = WorkflowState.from_payload(state.to_payload())
    assert rebuilt == state
    assert rebuilt.to_payload() == state.to_payload()


def test_schema_version_drift_fails_loudly() -> None:
    payload = _state().to_payload()
    payload["schema_version"] = "0"
    with pytest.raises(StateSchemaError):
        WorkflowState.from_payload(payload)


def test_initial_state_is_pending_at_intake() -> None:
    state = initial_workflow_state(
        "wf-2",
        workflow_type="feature-task",
        workflow_version="1",
        task_id="t-2",
        termination_policy="tp",
        approval_policy="ap",
    )
    assert state.status.state is WorkflowStatus.PENDING
    assert state.status.current_stage == "intake"
    assert state.status.termination_reason is None
    assert state.checkpoints.latest is None
    assert state.artifacts.patches == []
