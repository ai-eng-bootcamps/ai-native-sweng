"""Failure classification onto the canonical taxonomy (Lesson 7.1).

Both classifiers - the crash path over raised exceptions and the terminal path over
handled workflow outcomes - must produce the canonical section 8 class strings and
name the affected boundary. These fail against the scaffolding stubs and pass once
Module 7 is implemented to the reference behaviour.
"""

import pytest

from anse_harness.models.errors import ModelTimeoutError, ProviderError, ReplayExhaustedError
from anse_harness.reliability import classify_exception, classify_outcome
from anse_harness.runtime.sandbox import SandboxError
from anse_harness.state.store import StateStoreError
from anse_harness.tools.base import ToolError
from anse_harness.workflows.state import (
    StateSchemaError,
    WorkflowState,
    WorkflowStatus,
    initial_workflow_state,
)

pytestmark = pytest.mark.student_impl


def _terminal_state(status: WorkflowStatus, reason: str | None) -> WorkflowState:
    state = initial_workflow_state(
        "wf-x",
        workflow_type="feature-task",
        workflow_version="1",
        task_id="fx-x",
        termination_policy="t",
        approval_policy="a",
    )
    state.status.state = status
    state.status.termination_reason = reason
    return state


def test_model_timeout_is_a_retryable_model_provider_failure() -> None:
    classification = classify_exception(
        ModelTimeoutError("injected: request timed out", provider="injected")
    )
    assert classification.failure_class == "model-provider failure"
    assert classification.boundary == "model"
    assert classification.retryable is True
    assert classification.detail == "injected: request timed out"


def test_provider_error_carries_its_own_retryable_classification() -> None:
    permanent = classify_exception(
        ProviderError("invalid request", provider="p", retryable=False, status_code=400)
    )
    assert permanent.failure_class == "model-provider failure"
    assert permanent.retryable is False
    transient = classify_exception(
        ProviderError("server error", provider="p", retryable=True, status_code=500)
    )
    assert transient.retryable is True


def test_tool_error_is_a_tool_failure_at_the_tool_boundary() -> None:
    classification = classify_exception(ToolError("path escapes the repository root"))
    assert classification.failure_class == "tool failure"
    assert classification.boundary == "tool"
    assert classification.retryable is False


def test_infrastructure_boundaries_are_named() -> None:
    sandbox = classify_exception(SandboxError("cannot create worktree"))
    assert sandbox.failure_class == "transient infrastructure failure"
    assert sandbox.boundary == "sandbox"
    assert sandbox.retryable is True
    filesystem = classify_exception(OSError("disk unavailable"))
    assert filesystem.failure_class == "transient infrastructure failure"
    assert filesystem.boundary == "filesystem"


def test_corrupted_state_is_not_same_input_retryable() -> None:
    schema = classify_exception(StateSchemaError("schema version 'corrupted'"))
    assert schema.failure_class == "transient infrastructure failure"
    assert schema.boundary == "state store"
    assert schema.retryable is False
    missing = classify_exception(StateStoreError("no snapshots persisted"))
    assert missing.boundary == "state store"
    assert missing.retryable is False


def test_unknown_exceptions_are_persistent_unknown_failures() -> None:
    classification = classify_exception(RuntimeError("who knows"))
    assert classification.failure_class == "persistent unknown failure"
    assert classification.boundary == "unknown"
    assert classification.retryable is False
    # Harness replay errors carry no workflow meaning either; they classify as
    # unknown when forced through the classifier (the controller re-raises them
    # instead of classifying - see the controller tests).
    replay = classify_exception(ReplayExhaustedError("trace exhausted"))
    assert replay.failure_class == "persistent unknown failure"


def test_description_names_class_and_boundary() -> None:
    classification = classify_exception(ToolError("bad argument"))
    assert classification.describe() == "tool failure at the tool boundary: bad argument"


def test_outcome_classification_matches_the_rule_table() -> None:
    cases = [
        (WorkflowStatus.FAILED, "planning produced no steps", "malformed output", "model"),
        (
            WorkflowStatus.FAILED,
            "validation_failed: the validation report is not ok",
            "validation failure",
            "validation",
        ),
        (WorkflowStatus.CANCELLED, "plan_rejected: rejected", "policy denial", "approval"),
        (
            WorkflowStatus.FAILED,
            "patch_approval_rejected: rejected",
            "policy denial",
            "approval",
        ),
        (
            WorkflowStatus.ESCALATED,
            "implementation cost budget exhausted (0.02 of 0.01 USD)",
            "budget exhaustion",
            "budgets",
        ),
        (
            WorkflowStatus.ESCALATED,
            "review/fix loop stopped: no progress detected: the integrated patch and "
            "accepted findings repeated; 1 accepted finding(s) unresolved",
            "review failure",
            "review",
        ),
        (
            WorkflowStatus.FAILED,
            "implementation did not reach validation (status failed)",
            "implementation failure",
            "worker",
        ),
    ]
    for status, reason, expected_class, expected_boundary in cases:
        classification = classify_outcome(_terminal_state(status, reason))
        assert classification is not None, reason
        assert classification.failure_class == expected_class, reason
        assert classification.boundary == expected_boundary, reason
        assert classification.retryable is False
        assert classification.detail == reason


def test_outcome_classification_is_none_for_healthy_states() -> None:
    assert classify_outcome(_terminal_state(WorkflowStatus.COMPLETED, "completed")) is None
    assert classify_outcome(_terminal_state(WorkflowStatus.RUNNING, None)) is None
    assert classify_outcome(_terminal_state(WorkflowStatus.FAILED, None)) is None


def test_unmatched_terminal_reason_is_a_persistent_unknown_failure() -> None:
    classification = classify_outcome(
        _terminal_state(WorkflowStatus.FAILED, "something nobody anticipated")
    )
    assert classification is not None
    assert classification.failure_class == "persistent unknown failure"
    assert classification.boundary == "workflow"
