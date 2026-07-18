"""The stateful workflow engine: staged, persisted, resumable execution (spec 7.9).

Module 5 refactors "one bounded agent run" into an application-controlled workflow
(Lesson 5.1). The engine owns the stage graph

    Intake -> Investigate -> Plan -> Plan Approval -> Implement -> Validate
           -> Prepare Result

with the explicit terminal stages ``completed``, ``failed``, ``cancelled``, and
``escalated``. Every transition is validated against the transition table (Lesson 5.3;
architecture-reference 19) - an invalid transition raises, it is never silently
performed. Each stage boundary persists a numbered state snapshot through the
``WorkflowStateStore`` (Lesson 5.5), so an interrupted workflow resumes from its last
checkpoint, and a human can cancel a workflow into an explicit terminal state.

The stages CONSUME the earlier modules unchanged, which is what keeps every recorded
trace byte-stable:

* Investigate runs Module 4's context-driven loop over a packet built by Module 4's
  context builder;
* Plan is one model call under a pinned prompt (``workflows/plan.py``), producing a
  reviewable plan artifact (architecture-reference 32);
* Plan Approval reuses Module 3's ``ApprovalGate`` - deny by default, the workflow
  pauses at the boundary and a rejected plan cancels the workflow;
* Implement runs Module 3's safe write run (sandbox worktree, edit tools, validation,
  patch approval, rollback) with the approved plan folded into the task text;
* Validate judges the STRUCTURED validation report the write run produced - a failed
  validation can never reach the completed terminal (spec section 16, Module 5).

Module 2's ``runtime/loop.py``, Module 3's ``runtime/write_loop.py``, and Module 4's
``runtime/context_loop.py`` are untouched: the workflow lives entirely in this module
and is engaged only by constructing a ``WorkflowEngine`` (the same opt-in pattern that
kept the m02/m03/m04 traces byte-stable across module boundaries).

One workflow writes ONE trace file: the engine namespaces the event ids of the inner
loops (``StageTraceWriter``) so events from different stage runs stay unique within
the shared file, and emits its own ``state_transitioned`` and ``checkpoint_created``
events at every boundary.

``models/`` and ``tracing/`` are SUPPLIED infrastructure. The stage vocabulary, the
transition table, the specification and result types, the registries, and the trace
plumbing are supplied here too.

SCAFFOLDING: implement ``validate_transition`` in Module 5, Lesson 5.3, and
``WorkflowEngine.run``, ``WorkflowEngine.cancel``, and ``WorkflowEngine.resume``
across Module 5 (the staged run in Lessons 5.1-5.4, persistence, resume, and
cancellation in Lesson 5.5).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from anse_harness.approvals.gate import ApprovalGate
from anse_harness.models import ModelAdapter
from anse_harness.policy.commands import CommandPolicyEngine
from anse_harness.runtime.write_loop import WriteTaskResult
from anse_harness.state.store import WorkflowStateStore
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.create_file import CreateFileTool
from anse_harness.tools.delete_file import DeleteFileTool
from anse_harness.tools.inspect_diff import InspectDiffTool
from anse_harness.tools.inspect_git_status import InspectGitStatusTool
from anse_harness.tools.list_files import ListFilesTool
from anse_harness.tools.read_file import ReadFileTool
from anse_harness.tools.replace_text import ReplaceTextTool
from anse_harness.tools.run_read_only_command import RunReadOnlyCommandTool
from anse_harness.tools.run_validation_command import RunValidationCommandTool
from anse_harness.tools.search_text import SearchTextTool
from anse_harness.tracing import TraceEvent, TraceWriter
from anse_harness.validation.pipeline import ValidationCheck
from anse_harness.workflows.plan import PlanArtifact
from anse_harness.workflows.state import WorkflowState, initial_workflow_state

#: The workflow definition this engine implements (recorded in every state snapshot).
WORKFLOW_TYPE = "feature-task"
WORKFLOW_VERSION = "1"


class Stage(StrEnum):
    """The stages of the Module 5 reference workflow (spec section 16, Module 5)."""

    INTAKE = "intake"
    INVESTIGATE = "investigate"
    PLAN = "plan"
    PLAN_APPROVAL = "plan_approval"
    IMPLEMENT = "implement"
    VALIDATE = "validate"
    PREPARE_RESULT = "prepare_result"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


#: Stages in which the workflow is over. Terminal stages have no outgoing transitions.
TERMINAL_STAGES = frozenset({Stage.COMPLETED, Stage.FAILED, Stage.CANCELLED, Stage.ESCALATED})

#: The transition table (Lesson 5.3; architecture-reference 19). Cancellation is a
#: human action and is therefore reachable from EVERY non-terminal stage; escalation
#: is reachable from the model-driven stages (their cost budget hands off to a human).
TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    Stage.INTAKE: frozenset({Stage.INVESTIGATE, Stage.CANCELLED}),
    Stage.INVESTIGATE: frozenset({Stage.PLAN, Stage.FAILED, Stage.ESCALATED, Stage.CANCELLED}),
    Stage.PLAN: frozenset({Stage.PLAN_APPROVAL, Stage.FAILED, Stage.ESCALATED, Stage.CANCELLED}),
    Stage.PLAN_APPROVAL: frozenset({Stage.IMPLEMENT, Stage.CANCELLED}),
    Stage.IMPLEMENT: frozenset({Stage.VALIDATE, Stage.FAILED, Stage.ESCALATED, Stage.CANCELLED}),
    Stage.VALIDATE: frozenset({Stage.PREPARE_RESULT, Stage.FAILED, Stage.CANCELLED}),
    Stage.PREPARE_RESULT: frozenset({Stage.COMPLETED, Stage.FAILED, Stage.CANCELLED}),
    Stage.COMPLETED: frozenset(),
    Stage.FAILED: frozenset(),
    Stage.CANCELLED: frozenset(),
    Stage.ESCALATED: frozenset(),
}

#: Default validation checks for the implementation stage. git-based so recorded
#: fixture runs are deterministic and need no extra toolchain; a real target
#: configures its own checks (build, vet, tests) here instead.
DEFAULT_VALIDATION_CHECKS: tuple[ValidationCheck, ...] = (
    ValidationCheck("format-check", ("git", "diff", "--check")),
)


class WorkflowError(Exception):
    """The workflow cannot proceed (bad specification, terminal state, resume mismatch)."""


class InvalidTransitionError(WorkflowError):
    """A stage transition outside the transition table was attempted."""


def validate_transition(current: Stage, target: Stage) -> None:
    """Reject any transition the table does not allow (spec section 16, Module 5).

    Raises ``InvalidTransitionError``; a valid transition returns None. Terminal
    stages allow no outgoing transitions at all.
    """
    raise NotImplementedError(
        "Module 5, Lesson 5.3: look up TRANSITIONS[current]; if target is not in the "
        "allowed set, raise InvalidTransitionError naming the rejected transition."
    )


@dataclass(frozen=True)
class WorkflowTaskSpec:
    """The task one workflow serves: what to do and how the packet is built."""

    task_id: str
    description: str
    acceptance_criteria: tuple[str, ...]
    worker_type: str = "implementer"
    token_budget: int = 8000
    search_terms: tuple[str, ...] | None = None
    conflict_topics: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the task-specification artifact."""
        return {
            "artifact_type": "task_specification",
            "task_id": self.task_id,
            "description": self.description,
            "acceptance_criteria": list(self.acceptance_criteria),
            "worker_type": self.worker_type,
            "token_budget": self.token_budget,
            "search_terms": None if self.search_terms is None else list(self.search_terms),
            "conflict_topics": list(self.conflict_topics),
        }


@dataclass(frozen=True)
class WorkflowResult:
    """The outcome of one (possibly partial) workflow run.

    ``patch`` and ``validation_ok`` reflect the persisted artifacts, so a resumed
    workflow reports the same result the interrupted one would have.
    """

    state: WorkflowState
    investigation_answer: str | None
    plan: PlanArtifact | None
    patch: str | None
    validation_ok: bool | None
    result_artifact_id: str | None


def task_spec_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the task-specification artifact."""
    return f"task-spec-{task_id}"


def investigation_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the investigation-report artifact."""
    return f"investigation-{task_id}"


def plan_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the plan artifact."""
    return f"plan-{task_id}"


def patch_artifact_id(task_id: str, attempt: int) -> str:
    """Deterministic identifier of the patch artifact for one implementation attempt."""
    return f"patch-{task_id}-{attempt}"


def validation_artifact_id(task_id: str, attempt: int) -> str:
    """Deterministic identifier of the validation report for one implementation attempt."""
    return f"validation-{task_id}-{attempt}"


def result_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the final result artifact."""
    return f"result-{task_id}"


def build_investigation_registry(repo_root: Path) -> ToolRegistry:
    """The read-only tool set of the investigate stage, in the canonical order."""
    registry = ToolRegistry()
    registry.register(ListFilesTool(repo_root))
    registry.register(SearchTextTool(repo_root))
    registry.register(ReadFileTool(repo_root))
    registry.register(InspectGitStatusTool(repo_root))
    registry.register(RunReadOnlyCommandTool(repo_root))
    return registry


def build_implementation_registry(
    worktree_root: Path, policy: CommandPolicyEngine, gate: ApprovalGate
) -> ToolRegistry:
    """The write tool set of the implement stage, in the canonical order (Module 3)."""
    registry = ToolRegistry()
    registry.register(ListFilesTool(worktree_root))
    registry.register(SearchTextTool(worktree_root))
    registry.register(ReadFileTool(worktree_root))
    registry.register(InspectGitStatusTool(worktree_root))
    registry.register(CreateFileTool(worktree_root))
    registry.register(ReplaceTextTool(worktree_root))
    registry.register(DeleteFileTool(worktree_root, gate))
    registry.register(InspectDiffTool(worktree_root))
    registry.register(RunValidationCommandTool(worktree_root, policy))
    return registry


class StageTraceWriter(TraceWriter):
    """A per-stage view of a shared trace file that namespaces event identifiers.

    The inner loops assign their own sequential event ids starting at zero, so two
    stage runs written into one workflow trace would collide (and break the replay
    adapter's request/response pairing). This view rewrites ``event_id`` and
    ``parent_event_id`` with the stage run id before writing; the engine owns and
    closes the underlying writer.
    """

    def __init__(self, inner: TraceWriter, run_id: str) -> None:
        self._inner = inner
        self._run_prefix = run_id

    def write(self, event: TraceEvent) -> None:
        parent = event.parent_event_id
        self._inner.write(
            replace(
                event,
                event_id=f"{self._run_prefix}:{event.event_id}",
                parent_event_id=None if parent is None else f"{self._run_prefix}:{parent}",
            )
        )

    def close(self) -> None:
        """Closing a stage view is a no-op; the engine owns the underlying writer."""


class _Recorder:
    """Assigns sequential engine event ids and writes trace events, or no-ops."""

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


class WorkflowEngine:
    """Drives one workflow from intake to an explicit terminal stage.

    Construct with a fresh specification to start a new workflow, or through
    ``WorkflowEngine.resume`` to continue a persisted one from its latest checkpoint.
    """

    def __init__(
        self,
        spec: WorkflowTaskSpec,
        target_root: Path,
        adapter: ModelAdapter,
        store: WorkflowStateStore,
        *,
        gate: ApprovalGate | None = None,
        checks: Sequence[ValidationCheck] | None = None,
        workflow_id: str = "wf-m05-feature-task",
        investigate_max_iterations: int = 6,
        implement_max_iterations: int = 8,
        max_cost_usd: float | None = None,
        tracer: TraceWriter | None = None,
        clock: Callable[[], str] | None = None,
        state: WorkflowState | None = None,
    ) -> None:
        self._spec = spec
        self._target_root = target_root.resolve()
        self._adapter = adapter
        self._store = store
        self._gate = gate if gate is not None else ApprovalGate()
        self._checks = list(checks) if checks is not None else list(DEFAULT_VALIDATION_CHECKS)
        self._investigate_max_iterations = investigate_max_iterations
        self._implement_max_iterations = implement_max_iterations
        self._max_cost_usd = max_cost_usd
        self._tracer = tracer
        self._clock = clock
        if state is None:
            state = initial_workflow_state(
                workflow_id,
                workflow_type=WORKFLOW_TYPE,
                workflow_version=WORKFLOW_VERSION,
                task_id=spec.task_id,
                termination_policy=(
                    "explicit terminal stage required; per-stage iteration caps; "
                    "cost-budget exhaustion escalates"
                ),
                approval_policy=(
                    "plan and patch approvals resolved through the approval gate; deny by default"
                ),
            )
        self.state = state
        self._rec = _Recorder(tracer, f"run-{state.workflow_id}", state.workflow_id)
        self._elapsed_anchor = time.perf_counter()
        # In-memory stage results; a resumed engine reloads them from the store.
        self._investigation_answer: str | None = None
        self._plan: PlanArtifact | None = None
        self._write_result: WriteTaskResult | None = None

    @classmethod
    def resume(
        cls,
        store: WorkflowStateStore,
        workflow_id: str,
        *,
        spec: WorkflowTaskSpec,
        target_root: Path,
        adapter: ModelAdapter,
        gate: ApprovalGate | None = None,
        checks: Sequence[ValidationCheck] | None = None,
        investigate_max_iterations: int = 6,
        implement_max_iterations: int = 8,
        max_cost_usd: float | None = None,
        tracer: TraceWriter | None = None,
        clock: Callable[[], str] | None = None,
    ) -> WorkflowEngine:
        """Load a persisted workflow from its latest checkpoint and prepare to continue.

        Verifies, before anything runs (architecture-reference 52): the snapshot's
        state schema version (the store fails loudly on a mismatch), that the workflow
        is not already terminal, that the specification matches the persisted task,
        that the target repository is still at the checkpoint's revision, and that
        every artifact the state references is available. A resume record artifact is
        persisted and traced.
        """
        raise NotImplementedError(
            "Module 5, Lesson 5.5: load_latest from the store; raise WorkflowError for "
            "a terminal workflow, a task-id mismatch, a target HEAD that differs from "
            "the checkpoint's repository_revision, or a referenced artifact the store "
            "does not have; then build the engine around the loaded state, persist a "
            "resume_record artifact, and emit it as artifact_created."
        )

    def run(self, *, stop_after: Stage | None = None) -> WorkflowResult:
        """Drive the workflow from its current stage until a terminal stage.

        ``stop_after`` returns control after the named stage's boundary checkpoint
        instead of continuing - the deterministic stand-in for an interruption, since
        the state on disk is exactly what a killed process would have left behind.
        Raises ``WorkflowError`` when the workflow is already terminal.
        """
        raise NotImplementedError(
            "Module 5, Lessons 5.1-5.5: dispatch the current stage until a terminal "
            "stage is reached. Intake validates and records the specification; "
            "Investigate runs run_context_investigation over a packet from "
            "build_context_packet; Plan is one model call under PLAN_SYSTEM_PROMPT "
            "rendered by render_plan_request; Plan Approval routes the rendered plan "
            "through the ApprovalGate (rejection cancels); Implement runs "
            "run_write_task in a fresh sandbox with the plan folded in by "
            "render_implementation_task; Validate judges the structured validation "
            "report (failure can never complete); Prepare Result persists the result "
            "artifact. Every transition goes through validate_transition and every "
            "stage boundary saves a snapshot (checkpoint_created) plus "
            "state_transitioned trace events; give each inner loop a StageTraceWriter."
        )

    def cancel(self, reason: str) -> None:
        """Cancel the workflow: a human action, valid from every non-terminal stage.

        The workflow moves to the explicit ``cancelled`` terminal with the reason
        recorded, and a final checkpoint is persisted. Raises ``WorkflowError`` when
        the workflow is already terminal.
        """
        raise NotImplementedError(
            "Module 5, Lesson 5.5: raise WorkflowError when already terminal; "
            "otherwise transition to Stage.CANCELLED (valid from every non-terminal "
            "stage), set status cancelled with termination_reason "
            "'cancelled: <reason>', and persist a final checkpoint."
        )
