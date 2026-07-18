"""Retry decisions: intentional, ordered, and never blind (Lesson 7.2).

The decision function applies the documented checks in a fixed order, so the same
classified failure always produces the same decision and reason - most importantly,
a policy denial is never retried without a changed approval state (arch-ref 51).
These fail against the scaffolding stubs and pass once Module 7 is implemented.
"""

import pytest

from anse_harness.reliability import (
    DEFAULT_RETRY_POLICY,
    FailureClassification,
    RetryMode,
    RetryRule,
    decide_retry,
)

pytestmark = pytest.mark.student_impl


def _classified(
    failure_class: str, *, boundary: str = "model", retryable: bool = True
) -> FailureClassification:
    return FailureClassification(failure_class, boundary, retryable, "detail")


def test_transient_failure_is_retried_on_the_same_input() -> None:
    decision = decide_retry(DEFAULT_RETRY_POLICY, _classified("model-provider failure"), attempt=1)
    assert decision.action == "retry"
    assert decision.mode is RetryMode.SAME_INPUT
    assert decision.failed_attempt == 1
    assert decision.next_attempt == 2
    assert decision.reason == "same-input retry permitted: attempt 2 of 3"


def test_retry_budget_exhaustion_escalates() -> None:
    decision = decide_retry(DEFAULT_RETRY_POLICY, _classified("model-provider failure"), attempt=3)
    assert decision.action == "escalate"
    assert decision.mode is RetryMode.ESCALATE
    assert decision.next_attempt is None
    assert decision.reason == "retry budget exhausted: 3 of 3 attempts used"


def test_policy_denial_is_never_retried_without_changed_approval_state() -> None:
    denial = _classified("policy denial", boundary="approval", retryable=False)
    decision = decide_retry(DEFAULT_RETRY_POLICY, denial, attempt=1)
    assert decision.action == "escalate"
    assert (
        decision.reason
        == "policy denial is never retried without a changed approval or policy state"
    )
    # A changed approval state is the ONLY thing that permits the retry.
    permitted = decide_retry(DEFAULT_RETRY_POLICY, denial, attempt=1, approval_state_changed=True)
    assert permitted.action == "retry"
    assert permitted.mode is RetryMode.SAME_INPUT
    assert permitted.reason == "approval state changed; retry permitted"


def test_non_retryable_failure_is_not_blindly_re_run() -> None:
    permanent = _classified("model-provider failure", retryable=False)
    decision = decide_retry(DEFAULT_RETRY_POLICY, permanent, attempt=1)
    assert decision.action == "escalate"
    assert decision.reason == "non-retryable failure: a same-input retry would reproduce it"


def test_escalation_classes_escalate_by_policy() -> None:
    for failure_class in ("budget exhaustion", "integration conflict", "review failure"):
        decision = decide_retry(
            DEFAULT_RETRY_POLICY,
            _classified(failure_class, boundary="workflow", retryable=False),
            attempt=1,
        )
        assert decision.action == "escalate"
        assert decision.reason == f"{failure_class} escalates by policy"


def test_non_same_input_modes_travel_on_the_decision() -> None:
    malformed = _classified("malformed output", retryable=False)
    decision = decide_retry(DEFAULT_RETRY_POLICY, malformed, attempt=1)
    assert decision.action == "retry"
    assert decision.mode is RetryMode.FALLBACK_MODEL
    assert decision.reason == "alternative model permitted: attempt 2 of 2"
    replan = decide_retry(
        DEFAULT_RETRY_POLICY,
        _classified("implementation failure", boundary="worker", retryable=False),
        attempt=1,
    )
    assert replan.mode is RetryMode.REPLAN


def test_unknown_class_escalates_and_custom_tables_are_respected() -> None:
    unknown = decide_retry({}, _classified("model-provider failure"), attempt=1)
    assert unknown.action == "escalate"
    assert (
        unknown.reason == "failure class model-provider failure has no retry rule; human escalation"
    )
    tight = {"model-provider failure": RetryRule(RetryMode.SAME_INPUT, 2)}
    assert decide_retry(tight, _classified("model-provider failure"), attempt=1).action == ("retry")
    assert decide_retry(tight, _classified("model-provider failure"), attempt=2).action == (
        "escalate"
    )
