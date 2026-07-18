"""Supplied Module 7 reliability scaffolding: schemas, tables, and injection assets.

These validate the SUPPLIED contracts - the canonical taxonomy vocabulary, the
declarative retry table, the record payload round trips, the injection-spec asset
format, and the store corrupter - so the scaffolding itself stays green on a fresh
clone before any Module 7 exercise is implemented.
"""

import json
from pathlib import Path

import pytest

from anse_harness.models import ModelResponse, ScriptedAdapter, ScriptStep
from anse_harness.models.types import Usage
from anse_harness.reliability import (
    CANONICAL_FAILURE_CLASSES,
    DEFAULT_RETRY_POLICY,
    INJECTION_FAILURE_KINDS,
    AbortedRunReport,
    CircuitBreaker,
    EscalationRequest,
    FailureClassification,
    FailureInjectionAdapter,
    FailureRecord,
    InjectionSpec,
    RetryMode,
    aborted_run_artifact_id,
    corrupt_latest_snapshot,
    escalation_artifact_id,
    failure_artifact_id,
    injection_error,
    retry_artifact_id,
)
from anse_harness.reliability.policy import RetryDecision


def test_breaker_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        CircuitBreaker(threshold=0)
    assert CircuitBreaker(threshold=2).count("model") == 0


def test_canonical_failure_classes_are_the_fifteen_canonical_strings() -> None:
    assert len(CANONICAL_FAILURE_CLASSES) == 15
    assert CANONICAL_FAILURE_CLASSES[0] == "transient infrastructure failure"
    assert "model-provider failure" in CANONICAL_FAILURE_CLASSES
    assert "policy denial" in CANONICAL_FAILURE_CLASSES
    assert "persistent unknown failure" in CANONICAL_FAILURE_CLASSES
    # No vague labels: every entry is lower-case prose, no "agent" or "AI" language.
    for name in CANONICAL_FAILURE_CLASSES:
        assert name == name.lower()
        assert "agent" not in name
        assert "ai " not in name


def test_default_retry_policy_covers_every_canonical_class() -> None:
    assert set(DEFAULT_RETRY_POLICY) == set(CANONICAL_FAILURE_CLASSES)
    # Policy denial is never blindly retried (arch-ref 51).
    denial = DEFAULT_RETRY_POLICY["policy denial"]
    assert denial.mode is RetryMode.ESCALATE
    assert denial.max_attempts == 0
    # Transient faults are the same-input retry class.
    assert DEFAULT_RETRY_POLICY["model-provider failure"].mode is RetryMode.SAME_INPUT


def test_classification_and_record_payloads_round_trip() -> None:
    classification = FailureClassification(
        failure_class="model-provider failure",
        boundary="model",
        retryable=True,
        detail="injected: request timed out",
    )
    assert "model boundary" in classification.describe()
    assert FailureClassification.from_payload(classification.to_payload()) == classification
    record = FailureRecord(
        workflow_id="wf-x",
        task_id="fx-x",
        stage="implement",
        attempt=1,
        classification=classification,
    )
    payload = record.to_payload()
    assert payload["artifact_type"] == "failure_classification"
    assert payload["description"] == classification.describe()
    assert FailureRecord.from_payload(payload) == record


def test_retry_decision_payload_round_trips() -> None:
    decision = RetryDecision(
        action="retry",
        mode=RetryMode.SAME_INPUT,
        failure_class="model-provider failure",
        boundary="model",
        failed_attempt=1,
        next_attempt=2,
        reason="same-input retry permitted: attempt 2 of 3",
        observed_attempt_cost_usd=0.03,
    )
    payload = decision.to_payload()
    assert payload["artifact_type"] == "retry_decision"
    assert RetryDecision.from_payload(payload) == decision


def test_escalation_request_and_aborted_run_report_round_trip() -> None:
    report = AbortedRunReport(
        workflow_id="wf-x",
        task_id="fx-x",
        terminal_stage="escalated",
        termination_reason="circuit breaker open",
        failure_events=(("implement", "model-provider failure at the model boundary: t"),),
        monetary_used=0.05,
        token_used=1200,
        elapsed_seconds=1.5,
        worker_count=2,
        retry_count=1,
        surviving_artifacts=("task-spec-fx-x", "plan-fx-x"),
        unaccounted_attempt_cost_usd=0.06,
    )
    assert AbortedRunReport.from_payload(report.to_payload()) == report
    request = EscalationRequest(
        workflow_id="wf-x",
        task_id="fx-x",
        requested_action="review and decide: workflow wf-x stopped without completion",
        repository="repo",
        revision="abc123",
        artifact=aborted_run_artifact_id("fx-x"),
        risk_classification="class 0 - observation only (no further automated action)",
        validation_status="no validation report recorded",
        cost_impact_usd=0.05,
        reason="circuit breaker open",
        expiration_policy="does not expire; workflow remains terminal until a human acts",
        failure_history=("model-provider failure at the model boundary: t",),
        evidence_artifacts=("task-spec-fx-x",),
        trace_files=("attempt1.jsonl",),
    )
    assert EscalationRequest.from_payload(request.to_payload()) == request


def test_artifact_id_helpers_are_deterministic() -> None:
    assert failure_artifact_id("fx-x", 1) == "failure-fx-x-1"
    assert retry_artifact_id("fx-x", 2) == "retry-decision-fx-x-2"
    assert escalation_artifact_id("fx-x") == "escalation-request-fx-x"
    assert aborted_run_artifact_id("fx-x") == "aborted-run-fx-x"


def test_injection_spec_round_trips_and_validates(tmp_path: Path) -> None:
    spec = InjectionSpec(at_call=6, failure="model_timeout")
    assert spec.boundary == "model"
    assert InjectionSpec.from_payload(spec.to_payload()) == spec
    path = tmp_path / "spec.injection.json"
    spec.save(path)
    assert InjectionSpec.from_file(path) == spec
    with pytest.raises(ValueError, match="1-based"):
        InjectionSpec(at_call=0, failure="model_timeout")
    with pytest.raises(ValueError, match="unknown injection failure"):
        InjectionSpec(at_call=1, failure="tool_meltdown")
    with pytest.raises(ValueError, match="model boundary"):
        InjectionSpec(at_call=1, failure="model_timeout", boundary="tool")


def test_injection_error_kinds_map_to_provider_errors() -> None:
    for kind in INJECTION_FAILURE_KINDS:
        error = injection_error(kind)
        assert error.provider == "injected"
    assert injection_error("model_timeout").retryable is True
    assert injection_error("provider_error_retryable").retryable is True
    assert injection_error("provider_error_permanent").retryable is False
    with pytest.raises(ValueError, match="unknown injection failure"):
        injection_error("nope")


def test_injection_wrapper_capabilities_and_cost_pass_through() -> None:
    inner = ScriptedAdapter([ScriptStep(response=ModelResponse(text="one", usage=Usage(10, 5)))])
    adapter = FailureInjectionAdapter(inner, None)
    assert adapter.capabilities() == inner.capabilities()
    assert adapter.calculate_cost(Usage(1000, 100)) == inner.calculate_cost(Usage(1000, 100))


def test_committed_recovery_injection_spec_asset_is_loadable() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "traces"
        / "m07"
        / "recovery"
        / "attempt1.injection.json"
    )
    spec = InjectionSpec.from_file(path)
    assert spec == InjectionSpec(at_call=6, failure="model_timeout")


def test_corrupt_latest_snapshot_tampers_the_newest_snapshot(tmp_path: Path) -> None:
    snapshots = tmp_path / "wf-x" / "snapshots"
    snapshots.mkdir(parents=True)
    for version in (1, 2):
        (snapshots / f"state-v{version:04d}.json").write_text(
            json.dumps({"snapshot_version": version, "state": {"schema_version": "1"}}),
            encoding="utf-8",
        )
    corrupted = corrupt_latest_snapshot(tmp_path, "wf-x")
    assert corrupted.name == "state-v0002.json"
    document = json.loads(corrupted.read_text(encoding="utf-8"))
    assert document["state"]["schema_version"] == "corrupted"
    # The earlier snapshot is untouched.
    v1 = json.loads((tmp_path / "wf-x" / "snapshots" / "state-v0001.json").read_text())
    assert v1["state"]["schema_version"] == "1"
    with pytest.raises(FileNotFoundError):
        corrupt_latest_snapshot(tmp_path, "wf-missing")
