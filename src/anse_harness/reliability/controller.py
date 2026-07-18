"""Reliability controller: drive the unchanged engines through failure (Lessons 7.2-7.4).

The controller owns the retry-and-recover loop AROUND a workflow, using only public
surfaces: it runs attempts the caller constructs (a fresh ``WorkflowEngine`` for the
first, ``WorkflowEngine.resume`` for the rest), classifies whatever escapes them,
consults the retry policy and the circuit breaker, records every failure and every
decision as store artifacts, emits ``retry_scheduled`` through the trace writer, and
- when policy or breaker says stop - escalates through ``validate_transition`` and
``WorkflowStateStore.save``. The Module 5 engine and Module 6 orchestrator are not
forked, subclassed, or patched; ESCALATED is reachable from every non-terminal stage
precisely so an external controller can hand off to a human.

Attempt discipline (the Module 6 rule generalized): every attempt records into its
OWN trace file, replayed by its own ``ReplayAdapter`` - the engine's event ids
restart per instance, so appending a resumed run to an existing file would collide.
The reliability layer's ``budgets.retry_count`` is the count of RETRIES PERFORMED;
it is not the engine's attempt segment (a crashed implement records no invocation,
so the resumed implement legitimately reuses ``...-implement-1`` in its own file).

Escalation preserves evidence: the escalation-request artifact (arch-ref 55) and the
aborted-run report (spec 7.15) reference the surviving artifacts, the failure
history, the trace files, and the crashed attempts' observed spend - which the
workflow budgets do NOT contain (cost folds into state only at stage end), so the
report's ``unaccounted_attempt_cost_usd`` is where that honesty lives.

SCAFFOLDING: the record contracts, the recorder, and the cost reader are supplied;
implement ``ReliabilityController.execute``, ``escalate_workflow``,
``run_worker_attempts``, and ``idempotency_key`` in Module 7, Lessons 7.2-7.4.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from anse_harness.reliability.breaker import CircuitBreaker
from anse_harness.reliability.classify import FailureClassification
from anse_harness.reliability.policy import RetryDecision, RetryRule
from anse_harness.state.store import WorkflowStateStore
from anse_harness.tracing import TraceEvent, TraceWriter, read_trace
from anse_harness.workflows.engine import WorkflowResult
from anse_harness.workflows.state import WorkflowState

T = TypeVar("T")


def idempotency_key(task_id: str, workflow_id: str, action_type: str, artifact_version: str) -> str:
    """Derive the idempotency key of one repeatable external action (arch-ref 53).

    The key is derived from task id, workflow id, action type, and artifact
    version - the same action for the same artifact version always derives the
    same key, so a resumed workflow can detect that the action already ran instead
    of executing it twice. Format (pinned): ``"idem-"`` followed by the first 16
    hex digits of the SHA-256 of the four fields joined with newlines, in the
    parameter order above.
    """
    raise NotImplementedError(
        "Module 7, Lesson 7.4: return 'idem-' + "
        "sha256('\\n'.join(fields)).hexdigest()[:16] for the four fields in "
        "parameter order."
    )


def observed_cost_from_trace(trace_path: Path) -> float:
    """Total model spend recorded in one attempt's trace (its budget events).

    Sums the per-call ``cost_usd`` of every ``budget_updated`` event. For a
    crashed attempt this is spend the workflow state's budgets never saw - the
    retry-decision artifact carries it so it stays visible.
    """
    total = 0.0
    for event in read_trace(trace_path):
        if event.event_type == "budget_updated":
            total += float(event.payload.get("cost_usd", 0.0))
    return round(total, 10)


def escalation_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the escalation-request artifact."""
    return f"escalation-request-{task_id}"


def aborted_run_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the aborted-run report artifact."""
    return f"aborted-run-{task_id}"


@dataclass(frozen=True)
class EscalationRequest:
    """The escalation-request artifact: what a human needs to decide (arch-ref 55)."""

    workflow_id: str
    task_id: str
    requested_action: str
    #: Target repository NAME (never an absolute path - traces stay machine-neutral).
    repository: str
    revision: str
    #: The aborted-run report artifact accompanying this request.
    artifact: str
    risk_classification: str
    validation_status: str
    cost_impact_usd: float
    reason: str
    expiration_policy: str
    #: Every recorded failure reason, in order - the run's failure history.
    failure_history: tuple[str, ...]
    #: Persisted artifacts verified present: the evidence a human reviews.
    evidence_artifacts: tuple[str, ...]
    #: Trace files of the run's attempts (names, not paths).
    trace_files: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the escalation-request artifact."""
        return {
            "artifact_type": "escalation_request",
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "requested_action": self.requested_action,
            "repository": self.repository,
            "revision": self.revision,
            "artifact": self.artifact,
            "risk_classification": self.risk_classification,
            "validation_status": self.validation_status,
            "cost_impact_usd": self.cost_impact_usd,
            "reason": self.reason,
            "expiration_policy": self.expiration_policy,
            "failure_history": list(self.failure_history),
            "evidence_artifacts": list(self.evidence_artifacts),
            "trace_files": list(self.trace_files),
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> EscalationRequest:
        """Deserialize one artifact payload back into an EscalationRequest."""
        return cls(
            workflow_id=str(data["workflow_id"]),
            task_id=str(data["task_id"]),
            requested_action=str(data["requested_action"]),
            repository=str(data["repository"]),
            revision=str(data["revision"]),
            artifact=str(data["artifact"]),
            risk_classification=str(data["risk_classification"]),
            validation_status=str(data["validation_status"]),
            cost_impact_usd=float(data["cost_impact_usd"]),
            reason=str(data["reason"]),
            expiration_policy=str(data["expiration_policy"]),
            failure_history=tuple(str(item) for item in data["failure_history"]),
            evidence_artifacts=tuple(str(item) for item in data["evidence_artifacts"]),
            trace_files=tuple(str(item) for item in data["trace_files"]),
        )


@dataclass(frozen=True)
class AbortedRunReport:
    """The aborted-run report: partial results stay inspectable (spec 7.15)."""

    workflow_id: str
    task_id: str
    terminal_stage: str
    termination_reason: str
    #: (stage, reason) of every recorded failure, in order.
    failure_events: tuple[tuple[str, str], ...]
    monetary_used: float
    token_used: int
    elapsed_seconds: float
    worker_count: int
    retry_count: int
    #: Artifacts referenced by the state and verified present in the store.
    surviving_artifacts: tuple[str, ...]
    #: Crashed attempts' observed spend that the budgets above do NOT contain.
    unaccounted_attempt_cost_usd: float | None

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the aborted-run report artifact."""
        return {
            "artifact_type": "aborted_run_report",
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "terminal_stage": self.terminal_stage,
            "termination_reason": self.termination_reason,
            "failure_events": [
                {"stage": stage, "reason": reason} for stage, reason in self.failure_events
            ],
            "budgets": {
                "monetary_used": self.monetary_used,
                "token_used": self.token_used,
                "elapsed_seconds": self.elapsed_seconds,
                "worker_count": self.worker_count,
                "retry_count": self.retry_count,
            },
            "surviving_artifacts": list(self.surviving_artifacts),
            "unaccounted_attempt_cost_usd": self.unaccounted_attempt_cost_usd,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> AbortedRunReport:
        """Deserialize one artifact payload back into an AbortedRunReport."""
        budgets = dict(data["budgets"])
        cost = data.get("unaccounted_attempt_cost_usd")
        return cls(
            workflow_id=str(data["workflow_id"]),
            task_id=str(data["task_id"]),
            terminal_stage=str(data["terminal_stage"]),
            termination_reason=str(data["termination_reason"]),
            failure_events=tuple(
                (str(item["stage"]), str(item["reason"])) for item in data["failure_events"]
            ),
            monetary_used=float(budgets["monetary_used"]),
            token_used=int(budgets["token_used"]),
            elapsed_seconds=float(budgets["elapsed_seconds"]),
            worker_count=int(budgets["worker_count"]),
            retry_count=int(budgets["retry_count"]),
            surviving_artifacts=tuple(str(item) for item in data["surviving_artifacts"]),
            unaccounted_attempt_cost_usd=None if cost is None else float(cost),
        )


class _Recorder:
    """Assigns sequential namespaced event ids and writes trace events, or no-ops."""

    def __init__(
        self, writer: TraceWriter | None, run_id: str, workflow_id: str, prefix: str
    ) -> None:
        self._writer = writer
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._prefix = prefix
        self._seq = 0

    def emit(
        self,
        event_type: str,
        component: str,
        payload: dict[str, Any],
        *,
        status: str = "ok",
    ) -> str:
        event_id = f"{self._prefix}-{self._seq:04d}"
        self._seq += 1
        if self._writer is not None:
            self._writer.write(
                TraceEvent(
                    run_id=self._run_id,
                    workflow_id=self._workflow_id,
                    component=component,
                    event_type=event_type,
                    status=status,
                    payload=payload,
                    event_id=event_id,
                )
            )
        return event_id


@dataclass(frozen=True)
class RecoveryOutcome:
    """How one controller-supervised workflow ended."""

    #: The final attempt's result; None when the controller escalated instead.
    result: WorkflowResult | None
    #: Attempts actually run (the failed ones included).
    attempts: int
    #: True when the run ended at the escalated terminal (controller- or engine-driven).
    escalated: bool
    #: Every retry decision taken, in order.
    decisions: tuple[RetryDecision, ...]


class ReliabilityController:
    """Supervises one workflow's attempts: classify, decide, retry, or escalate.

    The controller never constructs engines itself - the caller's ``attempts``
    callable does (fresh engine for attempt 1, ``WorkflowEngine.resume`` after),
    which keeps adapter and trace-file wiring, including per-attempt replay,
    entirely in the caller's hands.
    """

    def __init__(
        self,
        store: WorkflowStateStore,
        workflow_id: str,
        *,
        policy: Mapping[str, RetryRule] | None = None,
        breaker: CircuitBreaker | None = None,
        tracer: TraceWriter | None = None,
    ) -> None:
        from anse_harness.reliability.policy import DEFAULT_RETRY_POLICY

        self._store = store
        self._workflow_id = workflow_id
        self._policy: dict[str, RetryRule] = dict(
            DEFAULT_RETRY_POLICY if policy is None else policy
        )
        self._breaker = breaker if breaker is not None else CircuitBreaker()
        self._tracer = tracer
        self._rec = _Recorder(tracer, f"run-{workflow_id}-reliability", workflow_id, "evt-rel")

    def execute(
        self,
        attempts: Callable[[int], WorkflowResult],
        *,
        target_root: Path,
        attempt_trace: Callable[[int], Path] | None = None,
    ) -> RecoveryOutcome:
        """Run attempts until one succeeds, the policy stops retrying, or the breaker opens.

        ``attempts(n)`` constructs and runs attempt ``n`` (1-based) and returns its
        ``WorkflowResult``; ``attempt_trace(n)``, when given, names the trace file
        attempt ``n`` recorded into (for observed-cost accounting). Per attempt:

        * **The attempt returns a result.** Record a success on the last failed
          boundary - or the model boundary when nothing failed - so the circuit
          closes. A failed/escalated/cancelled terminal was handled by the
          ENGINE: classify it with ``classify_outcome`` and, when a
          classification exists, persist a failure-classification artifact
          (``failure_artifact_id`` at the controller's failure ordinal) and
          emit ``artifact_created`` - but never mutate the state (the engine owns
          its own terminals) and never retry a terminal workflow (a terminal
          cannot resume; rerunning it is a NEW workflow, which is a human
          decision). Return the outcome (``escalated`` mirrors the terminal).
        * **The attempt raises a replay or script error.** ``ReplayError`` and
          ``ScriptError`` are HARNESS-DISCIPLINE errors, not workflow failures:
          re-raise them unclassified. A replay mismatch (or a raise-injected
          trace replayed without its injection spec) must stay LOUD - turning it
          into an escalation would bury the discipline signal.
        * **The attempt raises anything else.** Classify with
          ``classify_exception`` and record the failure on the breaker. Load the
          latest snapshot and append a
          ``FailureEvent(stage=current stage, reason=classification.describe())``.
          Read the failed attempt's observed cost when its trace is known.
          Persist the failure-classification artifact at the controller's
          failure ordinal - the 1-based count of failures THIS controller has
          classified - and emit ``artifact_created``. Take
          ``decide_retry(policy, classification, attempt=n)``; when the decision
          is retry but the breaker is open, override it with an escalate decision
          whose reason is ``"circuit breaker open: <count> consecutive failures
          at the <boundary> boundary"`` (same mode ``human escalation``). Stamp
          the observed cost into the decision, persist it
          (``retry_artifact_id``, same ordinal) and emit ``artifact_created``.
        * **Decision retry:** increment ``budgets.retry_count``, checkpoint the
          bookkeeping (stamp ``checkpoints.latest`` as the engine does, save with
          the target's HEAD revision, emit ``checkpoint_created``), emit
          ``retry_scheduled`` with payload ``{"failure_class", "retry_mode",
          "boundary", "failed_attempt", "next_attempt", "consecutive_failures"}``,
          and run the next attempt.
        * **Decision escalate:** checkpoint the bookkeeping the same way, then
          ``escalate_workflow`` with the decision's reason, the classification,
          every failure/retry artifact persisted so far as evidence, the known
          attempt trace file NAMES, and the unaccounted spend - the summed
          observed cost of the failed attempts MINUS ``budgets.monetary_used``
          (spend of stages that never completed, which the budgets never saw);
          return the outcome with ``result=None``.
        """
        raise NotImplementedError(
            "Module 7, Lessons 7.2-7.3: implement the documented attempt loop over "
            "classify_exception/classify_outcome, decide_retry, the breaker, the "
            "store bookkeeping, and escalate_workflow."
        )


def escalate_workflow(
    store: WorkflowStateStore,
    workflow_id: str,
    target_root: Path,
    *,
    reason: str,
    classification: FailureClassification,
    evidence_artifacts: tuple[str, ...] = (),
    trace_files: tuple[str, ...] = (),
    unaccounted_attempt_cost_usd: float | None = None,
    tracer: TraceWriter | None = None,
) -> WorkflowState:
    """Move a persisted non-terminal workflow to the escalated terminal, with evidence.

    Uses ONLY public surfaces - this reproduces the engine's escalation semantics
    from outside, for controller-detected conditions. In order:

    1. Load the latest snapshot and validate the transition from the current stage
       to ``Stage.ESCALATED`` (legal from every non-terminal stage by design).
    2. Collect the surviving artifacts: the state's referenced ids (specification,
       plan, patches, validation reports) followed by ``evidence_artifacts``,
       deduplicated in order, keeping only those ``store.has_artifact`` confirms.
    3. Persist the aborted-run report (``aborted_run_artifact_id``): terminal
       stage ``"escalated"``, the reason, the state's failure events and budgets,
       the surviving artifacts, and the unaccounted attempt cost. Emit
       ``artifact_created``.
    4. Persist the escalation request (``escalation_artifact_id``): requested
       action ``"review and decide: workflow <workflow_id> stopped without
       completion"``, repository = the target root's NAME (never a path),
       revision = the target's HEAD, artifact = the aborted-run report id, risk
       classification ``"class 0 - observation only (no further automated
       action)"``, validation status = the latest validation report id or ``"no
       validation report recorded"``, cost impact = ``budgets.monetary_used``,
       the reason, expiration policy ``"does not expire; workflow remains
       terminal until a human acts"``, failure history = every recorded failure
       reason, the surviving artifacts as evidence, and the trace file names.
       Emit ``artifact_created``.
    5. Move the state to the terminal - status escalated, termination reason,
       current stage ``escalated`` - stamp ``checkpoints.latest``
       (``cp-<workflow_id>-v<version:04d>`` from ``store.next_version``), save
       with the HEAD revision, emit ``escalation_created`` (payload ``{"reason",
       "failure_class", "boundary"}``, status ``"error"``) and
       ``checkpoint_created``.

    Events use the ``evt-esc`` id namespace so a controller sharing the trace
    writer never collides. Returns the terminal state.
    """
    raise NotImplementedError(
        "Module 7, Lesson 7.3: implement the five documented steps over "
        "validate_transition, has_artifact, save_artifact, and save."
    )


def run_worker_attempts(
    invoke: Callable[[int], T],
    *,
    policy: Mapping[str, RetryRule] | None = None,
    breaker: CircuitBreaker | None = None,
    start_attempt: int = 1,
) -> tuple[T, int, tuple[RetryDecision, ...]]:
    """Retry one worker invocation with a BUMPED ATTEMPT SEGMENT per try (Lesson 7.3).

    ``invoke(attempt)`` runs the worker under that attempt number - Module 6's
    ``attempt`` parameter namespaces the run ids, event ids, trace file, and
    sandbox branch, so a retried worker NEVER collides with its failed attempt's
    residue. This is the whole reason the parameter exists.

    On success returns ``(result, attempt, decisions)``. On a ``ReplayError`` or
    ``ScriptError``: re-raise it unclassified, BEFORE any classification or
    breaker bookkeeping - harness-discipline errors are not worker failures and
    must stay loud (the same rule as ``ReliabilityController.execute``). On any
    other exception: classify it, record the failure on the breaker (when given),
    and take ``decide_retry(policy, classification, attempt=tries so far)``; when
    the decision is retry AND the breaker is not open for the classification's
    boundary, invoke again with ``attempt + 1``; otherwise re-raise the original
    exception - the caller owns escalation. The default policy is
    ``DEFAULT_RETRY_POLICY``.
    """
    raise NotImplementedError(
        "Module 7, Lesson 7.3: loop invoke(attempt) from start_attempt; classify "
        "exceptions, consult decide_retry and the breaker, bump the attempt "
        "segment on retry, and re-raise the original failure when retrying stops."
    )


__all__ = [
    "AbortedRunReport",
    "EscalationRequest",
    "RecoveryOutcome",
    "ReliabilityController",
    "aborted_run_artifact_id",
    "escalate_workflow",
    "escalation_artifact_id",
    "idempotency_key",
    "observed_cost_from_trace",
    "run_worker_attempts",
]
