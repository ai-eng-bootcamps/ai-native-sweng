"""Reliability: classify failures, retry deliberately, resume safely, escalate with evidence (M7).

Agentic workflows fail in ways request-response systems do not expose: a provider
times out mid-stage, a worker produces nothing, a checkpoint is interrupted, a fix
loop stops making progress. Module 7 makes workflows bounded, diagnosable,
resumable, and recoverable - WITHOUT changing the engines built in Modules 5 and 6.
Everything here drives their public surfaces from the outside:

* ``classify.py`` - the canonical failure taxonomy (canonical-reference section 8)
  and the classifiers that map raised exceptions and terminal workflow states onto
  it (Lesson 7.1);
* ``policy.py`` - the declarative retry table and the retry decision rules
  (architecture-reference section 51), plus the window-based no-progress detector
  (Lessons 7.2 and 7.5);
* ``breaker.py`` - the circuit breaker: consecutive-failure counting per boundary
  (Lesson 7.5);
* ``controller.py`` - the reliability controller that drives run/resume cycles of
  the unchanged workflow engine, retries workers with a bumped attempt segment,
  and escalates through the public state-store surface with its evidence preserved
  (Lessons 7.2-7.4);
* ``injection.py`` - the failure-injection harness (Lesson 7.6): content failures
  belong in the SCRIPT and replay for free; provider raises are declarative
  ``InjectionSpec`` configuration applied identically when recording and when
  replaying; checkpoint corruption is injected at the store's files.
"""

from anse_harness.reliability.breaker import CircuitBreaker
from anse_harness.reliability.classify import (
    CANONICAL_FAILURE_CLASSES,
    OUTCOME_RULES,
    FailureClassification,
    FailureRecord,
    classify_exception,
    classify_outcome,
    failure_artifact_id,
)
from anse_harness.reliability.controller import (
    AbortedRunReport,
    EscalationRequest,
    RecoveryOutcome,
    ReliabilityController,
    aborted_run_artifact_id,
    escalate_workflow,
    escalation_artifact_id,
    idempotency_key,
    observed_cost_from_trace,
    run_worker_attempts,
)
from anse_harness.reliability.injection import (
    INJECTION_FAILURE_KINDS,
    FailureInjectionAdapter,
    InjectionSpec,
    corrupt_latest_snapshot,
    injection_error,
)
from anse_harness.reliability.policy import (
    DEFAULT_RETRY_POLICY,
    RetryDecision,
    RetryMode,
    RetryRule,
    decide_retry,
    detect_no_progress_window,
    retry_artifact_id,
)

__all__ = [
    "CANONICAL_FAILURE_CLASSES",
    "DEFAULT_RETRY_POLICY",
    "INJECTION_FAILURE_KINDS",
    "OUTCOME_RULES",
    "AbortedRunReport",
    "CircuitBreaker",
    "EscalationRequest",
    "FailureClassification",
    "FailureInjectionAdapter",
    "FailureRecord",
    "InjectionSpec",
    "RecoveryOutcome",
    "ReliabilityController",
    "RetryDecision",
    "RetryMode",
    "RetryRule",
    "aborted_run_artifact_id",
    "classify_exception",
    "classify_outcome",
    "corrupt_latest_snapshot",
    "decide_retry",
    "detect_no_progress_window",
    "escalate_workflow",
    "escalation_artifact_id",
    "failure_artifact_id",
    "idempotency_key",
    "injection_error",
    "observed_cost_from_trace",
    "retry_artifact_id",
    "run_worker_attempts",
]
