"""The multi-worker orchestrator: fan-out, integration, review, and fix loops (Module 6).

Module 5 built a stateful workflow around ONE worker; Module 6 makes the workflow a
coordinator of MANY short-lived workers (arch-ref 16). The orchestrator owns the stage
graph

    Intake -> Fan-Out -> Integrate -> Validate -> Review -> Consolidate
           -> Fix -> (Validate -> Review -> ...) -> Prepare Result

with the explicit terminals ``completed``, ``failed``, ``cancelled``, and
``escalated``. Intake validates the task GRAPH (arch-ref 34) before anything runs;
Fan-Out instantiates one fresh implementation worker per graph node; Integrate applies
their patches deterministically in graph order onto an integration worktree (arch-ref
37); Validate runs the deterministic validation pipeline over the INTEGRATED result;
Review fans out fresh, read-only reviewers over it; Consolidate applies the evidence
gate, deduplication, and conflict marking; Fix instantiates fresh fix workers from the
accepted findings; and the loop repeats under an explicit termination policy with
no-progress detection (arch-ref 45, 48, 49). Targeted re-review (arch-ref 47): after a
fix round, only the reviewers whose accepted findings were fixed run again.

Replay discipline (the Module 6 determinism boundary): every worker runs against its
OWN adapter and writes its OWN trace file, so the orchestrator takes an adapter
FACTORY - ``(worker_id, stage, attempt) -> ModelAdapter`` - instead of one adapter,
and an optional tracer factory with the same key. Scripted and replayed runs use
``max_concurrency=1`` and schedule workers in graph order; live runs raise the bound
through the SAME code path. Fan-in always records results in graph order, never in
completion order, so the workflow state and the orchestrator's own trace are
deterministic regardless of scheduling.

Budgets aggregate exactly as in Module 5: every worker invocation's cost folds into
``budgets.monetary_used``, and the state schema is the UNCHANGED canonical section 13
schema at version 1 - worker lineage beyond the compact invocation entries persists as
canonical 9.2 artifacts (``invocation-<worker>-<stage>-<n>``).

The Module 5 engine, loops, sandbox manager, and state store are consumed through
their public APIs, byte-untouched; multi-worker execution lives entirely in this
module and its Module 6 siblings, engaged only by constructing a
``MultiWorkerOrchestrator``.

``models/`` and ``tracing/`` are SUPPLIED infrastructure. SCAFFOLDING: the stage
graph, specifications, identifiers, and constructor are supplied; implement ``run``
and ``cancel`` in Module 6, Lessons 6.4 and 6.8 (with the pieces you build in the
sibling modules along the way).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from anse_harness.approvals.gate import ApprovalGate
from anse_harness.budgets.policy import LoopSnapshot, TerminationPolicy
from anse_harness.models import ModelAdapter
from anse_harness.review.consolidation import ConsolidatedReview
from anse_harness.review.findings import ReviewFinding
from anse_harness.state.store import WorkflowStateStore
from anse_harness.tracing import TraceEvent, TraceWriter
from anse_harness.validation.pipeline import ValidationCheck
from anse_harness.workflows.engine import DEFAULT_VALIDATION_CHECKS
from anse_harness.workflows.graph import TaskGraph
from anse_harness.workflows.integration import IntegrationResult, OverlapPolicy
from anse_harness.workflows.state import (
    WorkflowState,
    initial_workflow_state,
)

#: The workflow definition this orchestrator implements (recorded in every snapshot).
MULTIWORKER_WORKFLOW_TYPE = "multiworker-feature-task"
MULTIWORKER_WORKFLOW_VERSION = "1"

#: Default workflow id; names the orchestrator run id and the sandbox branches.
DEFAULT_MULTIWORKER_WORKFLOW_ID = "wf-m06-multiworker"

#: An adapter per worker invocation: ``(worker_id, stage, attempt) -> adapter``.
#: Record mode hands each worker its script; replay mode hands each worker the
#: ReplayAdapter over its own trace file.
AdapterFactory = Callable[[str, str, int], ModelAdapter]

#: A trace writer per worker invocation, same key; None disables that worker's trace.
TracerFactory = Callable[[str, str, int], "TraceWriter | None"]


class MultiStage(StrEnum):
    """The stages of the Module 6 multi-worker workflow (spec section 16, Module 6)."""

    INTAKE = "intake"
    FAN_OUT = "fan_out"
    INTEGRATE = "integrate"
    VALIDATE = "validate"
    REVIEW = "review"
    CONSOLIDATE = "consolidate"
    FIX = "fix"
    PREPARE_RESULT = "prepare_result"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


#: Stages in which the workflow is over. Terminal stages have no outgoing transitions.
MULTI_TERMINAL_STAGES = frozenset(
    {MultiStage.COMPLETED, MultiStage.FAILED, MultiStage.CANCELLED, MultiStage.ESCALATED}
)

#: The transition table (arch-ref 19 discipline over the arch-ref 45 loop).
#: Cancellation is a human action, reachable from every non-terminal stage.
#: ``FIX -> VALIDATE -> REVIEW`` is the revalidate/re-review edge of the loop;
#: ``CONSOLIDATE`` either completes the loop (no accepted findings), permits another
#: fix round, or escalates (termination policy, no-progress, conflicting findings).
MULTI_TRANSITIONS: dict[MultiStage, frozenset[MultiStage]] = {
    MultiStage.INTAKE: frozenset({MultiStage.FAN_OUT, MultiStage.CANCELLED}),
    MultiStage.FAN_OUT: frozenset(
        {MultiStage.INTEGRATE, MultiStage.FAILED, MultiStage.ESCALATED, MultiStage.CANCELLED}
    ),
    MultiStage.INTEGRATE: frozenset(
        {MultiStage.VALIDATE, MultiStage.FAILED, MultiStage.ESCALATED, MultiStage.CANCELLED}
    ),
    MultiStage.VALIDATE: frozenset({MultiStage.REVIEW, MultiStage.FAILED, MultiStage.CANCELLED}),
    MultiStage.REVIEW: frozenset(
        {MultiStage.CONSOLIDATE, MultiStage.FAILED, MultiStage.ESCALATED, MultiStage.CANCELLED}
    ),
    MultiStage.CONSOLIDATE: frozenset(
        {
            MultiStage.FIX,
            MultiStage.PREPARE_RESULT,
            MultiStage.ESCALATED,
            MultiStage.CANCELLED,
        }
    ),
    MultiStage.FIX: frozenset(
        {MultiStage.VALIDATE, MultiStage.FAILED, MultiStage.ESCALATED, MultiStage.CANCELLED}
    ),
    MultiStage.PREPARE_RESULT: frozenset(
        {MultiStage.COMPLETED, MultiStage.FAILED, MultiStage.CANCELLED}
    ),
    MultiStage.COMPLETED: frozenset(),
    MultiStage.FAILED: frozenset(),
    MultiStage.CANCELLED: frozenset(),
    MultiStage.ESCALATED: frozenset(),
}


class MultiWorkflowError(Exception):
    """The multi-worker workflow cannot proceed (bad specification, terminal state)."""


class InvalidMultiTransitionError(MultiWorkflowError):
    """A stage transition outside the multi-worker transition table was attempted."""


def validate_multiworker_transition(current: MultiStage, target: MultiStage) -> None:
    """Reject any transition the table does not allow (the Module 5 rule, new table)."""
    allowed = MULTI_TRANSITIONS[current]
    if target not in allowed:
        raise InvalidMultiTransitionError(
            f"invalid multi-worker transition {current.value!r} -> {target.value!r}; "
            f"allowed: {sorted(stage.value for stage in allowed)}"
        )


@dataclass(frozen=True)
class ReviewerSpec:
    """One reviewer the workflow runs: a fresh instance specialized by concern."""

    reviewer_id: str
    #: A finding category: ``correctness``, ``tests``, ``maintainability``, ...
    concern: str


@dataclass(frozen=True)
class MultiWorkerSpec:
    """The task one multi-worker workflow serves, with its decomposition and reviewers."""

    task_id: str
    description: str
    acceptance_criteria: tuple[str, ...]
    graph: TaskGraph
    reviewers: tuple[ReviewerSpec, ...]
    token_budget: int = 8000

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the task-specification artifact."""
        return {
            "artifact_type": "task_specification",
            "task_id": self.task_id,
            "description": self.description,
            "acceptance_criteria": list(self.acceptance_criteria),
            "reviewers": [
                {"reviewer_id": reviewer.reviewer_id, "concern": reviewer.concern}
                for reviewer in self.reviewers
            ],
            "token_budget": self.token_budget,
        }


@dataclass(frozen=True)
class MultiWorkerResult:
    """The outcome of one multi-worker workflow run."""

    state: WorkflowState
    #: The execution/integration order derived from the task graph.
    graph_order: tuple[str, ...]
    #: Each implementation worker's approved patch, by worker id.
    worker_patches: dict[str, str] = field(default_factory=dict)
    #: The final integrated patch (after any fix rounds); None before integration.
    integrated_patch: str | None = None
    #: Every finding reported across all review rounds, in report order.
    findings: tuple[ReviewFinding, ...] = ()
    #: The final round's consolidated review.
    consolidated: ConsolidatedReview | None = None
    review_iterations: int = 0
    validation_ok: bool | None = None
    result_artifact_id: str | None = None


# ── Worker-scoped artifact identifiers ──────────────────────────────────────────────
# Module 5's helpers are task+attempt scoped; two workers on the same parent task
# would collide (the spike's measured finding). Module 6's identifiers carry the
# worker segment. The Module 5 helpers are untouched.


def task_graph_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the task-graph artifact."""
    return f"task-graph-{task_id}"


def worker_patch_artifact_id(task_id: str, worker_id: str, attempt: int) -> str:
    """Deterministic identifier of one worker's patch artifact."""
    return f"patch-{task_id}-{worker_id}-{attempt}"


def worker_validation_artifact_id(task_id: str, worker_id: str, attempt: int) -> str:
    """Deterministic identifier of one worker's validation-report artifact."""
    return f"validation-{task_id}-{worker_id}-{attempt}"


def invocation_artifact_id(worker_id: str, stage: str, attempt: int) -> str:
    """Deterministic identifier of one canonical 9.2 invocation-record artifact."""
    return f"invocation-{worker_id}-{stage}-{attempt}"


def integration_artifact_id(task_id: str, round_number: int) -> str:
    """Deterministic identifier of one integration-report artifact."""
    return f"integration-{task_id}-{round_number}"


def integrated_validation_artifact_id(task_id: str, round_number: int) -> str:
    """Deterministic identifier of one integrated-validation-report artifact."""
    return f"validation-{task_id}-integrated-{round_number}"


def findings_artifact_id(task_id: str, reviewer_id: str, iteration: int) -> str:
    """Deterministic identifier of one reviewer round's findings artifact."""
    return f"findings-{task_id}-{reviewer_id}-{iteration}"


def consolidated_review_artifact_id(task_id: str, iteration: int) -> str:
    """Deterministic identifier of one round's consolidated-review artifact."""
    return f"consolidated-review-{task_id}-{iteration}"


def termination_report_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the termination-report artifact."""
    return f"termination-report-{task_id}"


def multi_result_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the final multi-worker result artifact."""
    return f"result-{task_id}"


def worker_trace_filename(worker_id: str, attempt: int = 1) -> str:
    """The canonical trace file name of one worker invocation (``traces/m06/...``).

    First invocations map to ``<worker_id>.jsonl`` (hyphens as underscores); a
    re-invocation - a later review round, a retry - maps to
    ``<worker_id>_round_<attempt>.jsonl``, because every invocation writes its OWN
    file (the per-worker-file replay layout).
    """
    base = worker_id.replace("-", "_")
    if attempt == 1:
        return f"{base}.jsonl"
    return f"{base}_round_{attempt}.jsonl"


class _Recorder:
    """Assigns sequential orchestrator event ids and writes trace events, or no-ops."""

    def __init__(self, writer: TraceWriter | None, run_id: str, workflow_id: str) -> None:
        self._writer = writer
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._seq = 0

    def emit(
        self,
        event_type: str,
        component: str,
        payload: dict[str, object],
        *,
        parent: str | None = None,
        status: str = "ok",
    ) -> str:
        event_id = f"evt-wf-{self._seq:04d}"
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
                    parent_event_id=parent,
                )
            )
        return event_id


class MultiWorkerOrchestrator:
    """Drives one multi-worker workflow from intake to an explicit terminal stage."""

    def __init__(
        self,
        spec: MultiWorkerSpec,
        target_root: Path,
        adapters: AdapterFactory,
        store: WorkflowStateStore,
        *,
        gate: ApprovalGate | None = None,
        checks: Sequence[ValidationCheck] | None = None,
        workflow_id: str = DEFAULT_MULTIWORKER_WORKFLOW_ID,
        max_concurrency: int = 1,
        termination: TerminationPolicy | None = None,
        overlap_policy: OverlapPolicy | None = None,
        worker_cost_budget_usd: float = 1.0,
        model_configuration: str = "scripted",
        tracer: TraceWriter | None = None,
        worker_tracers: TracerFactory | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._spec = spec
        self._target_root = target_root.resolve()
        self._adapters = adapters
        self._store = store
        self._gate = gate if gate is not None else ApprovalGate()
        self._checks = list(checks) if checks is not None else list(DEFAULT_VALIDATION_CHECKS)
        self._max_concurrency = max_concurrency
        self._termination = termination if termination is not None else TerminationPolicy()
        self._overlap_policy = overlap_policy if overlap_policy is not None else OverlapPolicy()
        self._worker_cost_budget_usd = worker_cost_budget_usd
        self._model_configuration = model_configuration
        self._tracer = tracer
        self._worker_tracers = worker_tracers
        self._clock = clock
        self.state = initial_workflow_state(
            workflow_id,
            workflow_type=MULTIWORKER_WORKFLOW_TYPE,
            workflow_version=MULTIWORKER_WORKFLOW_VERSION,
            task_id=spec.task_id,
            termination_policy=self._termination.describe(),
            approval_policy=(
                "patch approvals resolved through the approval gate per worker; deny by default"
            ),
        )
        self._rec = _Recorder(tracer, f"run-{workflow_id}", workflow_id)
        # In-memory progress of one run; the orchestrator is single-run (Module 7
        # brings resumability to multi-worker execution).
        self._order: tuple[str, ...] = ()
        self._worker_patches: dict[str, str] = {}
        self._integration: IntegrationResult | None = None
        self._all_findings: list[ReviewFinding] = []
        self._round_findings: tuple[ReviewFinding, ...] = ()
        self._consolidated: ConsolidatedReview | None = None
        self._iteration = 0
        self._previous_snapshot: LoopSnapshot | None = None
        self._rereview_scope: tuple[str, ...] | None = None
        self._fix_count = 0
        self._validation_ok: bool | None = None

    def run(self) -> MultiWorkerResult:
        """Drive the workflow from intake until a terminal stage.

        Fan-out concurrency is bounded by ``max_concurrency`` through one code path:
        scripted and replayed runs use bound 1 (graph order); live runs raise the
        bound. Fan-in records worker results in graph order regardless of completion
        order. Raises ``MultiWorkflowError`` when the workflow is already terminal.
        The integration worktree is destroyed before this method returns.
        """
        raise NotImplementedError(
            "Module 6, Lessons 6.3-6.9: validate the graph and persist the task "
            "specification and task-graph artifacts (intake); fan out one fresh "
            "implementation worker per node under the concurrency bound and record "
            "results in graph order; integrate patches in graph order with overlap "
            "detection and conflict evidence; validate the integrated result; fan "
            "out fresh reviewers; consolidate findings; assign fresh fix workers "
            "to accepted findings and loop under the termination policy with "
            "no-progress detection and targeted re-review; checkpoint every stage "
            "boundary; end in an explicit terminal stage."
        )

    def cancel(self, reason: str) -> None:
        """Cancel the workflow: a human action, valid from every non-terminal stage."""
        raise NotImplementedError(
            "Module 6, Lesson 6.8: refuse when terminal; transition to CANCELLED, "
            "set the status and termination reason ('cancelled: <reason>'), and "
            "persist a final checkpoint - exactly the Module 5 cancellation "
            "discipline on the Module 6 stage graph."
        )
