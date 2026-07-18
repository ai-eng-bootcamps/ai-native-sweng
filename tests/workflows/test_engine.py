"""End-to-end tests for the stateful workflow engine (Lessons 5.1-5.5).

A scripted model drives the whole stage graph over the committed Module 5 fixture:
intake, context-driven investigation, one planning call, the plan-approval boundary,
the sandboxed write run, deterministic validation judgment, and result preparation -
with a checkpoint at every boundary and an explicit terminal on every path. These
fail against the scaffolding stubs and pass once the store and the engine are
implemented to the reference behaviour.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalRequest,
    approve_all,
)
from anse_harness.models import CostTable, ModelResponse, ScriptedAdapter, ScriptStep, ToolCall
from anse_harness.models.types import Usage
from anse_harness.state.store import WorkflowStateStore
from anse_harness.tracing import TraceWriter, read_trace
from anse_harness.workflows.engine import (
    Stage,
    WorkflowEngine,
    WorkflowError,
    WorkflowTaskSpec,
)
from anse_harness.workflows.state import WorkflowStatus

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m05"

SPEC = WorkflowTaskSpec(
    task_id="fx-venue-slug",
    description=(
        "Venue directory slugs must match the documented format: the venue name "
        "trimmed, lowercased, and with spaces replaced by hyphens."
    ),
    acceptance_criteria=('Slug("Main Hall") returns "main-hall".',),
    search_terms=("slug",),
)

OLD_RETURN = "return strings.ToLower(strings.TrimSpace(name))"
NEW_RETURN = 'return strings.ReplaceAll(strings.ToLower(strings.TrimSpace(name)), " ", "-")'


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """The Module 5 fixture tree, materialized as a one-commit git repository."""
    repo = tmp_path / "target"
    shutil.copytree(FIXTURES / "repo", repo)
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "base"],
    ):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)
    return repo


def _answer(text: str) -> ScriptStep:
    return ScriptStep(response=ModelResponse(text=text, usage=Usage(100, 20)))


def _edit(new_text: str = NEW_RETURN) -> ScriptStep:
    return ScriptStep(
        response=ModelResponse(
            text="Editing the slug rule.",
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="replace_text",
                    arguments={
                        "path": "internal/directory/slug.go",
                        "old_text": OLD_RETURN,
                        "new_text": new_text,
                    },
                )
            ],
            usage=Usage(100, 30),
            stop_reason="tool_use",
        )
    )


def _adapter(steps: list[ScriptStep]) -> ScriptedAdapter:
    return ScriptedAdapter(
        steps, cost_table=CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)
    )


def _happy_steps() -> list[ScriptStep]:
    """Investigate answers directly, planning replies with steps, implement edits."""
    return [
        _answer("The slug rule lives in internal/directory/slug.go and never adds hyphens."),
        _answer("1. Extend the return expression in internal/directory/slug.go."),
        _edit(),
        _answer("Extended the slug rule to replace spaces with hyphens, as planned."),
    ]


def _engine(
    target: Path,
    store: WorkflowStateStore,
    steps: list[ScriptStep],
    *,
    gate: ApprovalGate | None = None,
    tracer: TraceWriter | None = None,
) -> WorkflowEngine:
    return WorkflowEngine(
        SPEC,
        target,
        _adapter(steps),
        store,
        gate=gate if gate is not None else ApprovalGate(approve_all),
        max_cost_usd=1.0,
        tracer=tracer,
    )


def _git_status(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _no_worktrees_left(target: Path) -> bool:
    """Every sandbox worktree was destroyed (the container directory may remain)."""
    worktrees = target.parent / ".anse-worktrees"
    return not worktrees.exists() or not any(worktrees.iterdir())


def test_full_run_reaches_the_completed_terminal(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    trace_path = tmp_path / "workflow.jsonl"
    with TraceWriter(trace_path) as writer:
        result = _engine(target, store, _happy_steps(), tracer=writer).run()

    state = result.state
    assert state.status.state is WorkflowStatus.COMPLETED
    assert state.status.current_stage == Stage.COMPLETED.value
    assert state.status.termination_reason == "completed"
    assert result.validation_ok is True
    assert result.patch is not None and "ReplaceAll" in result.patch
    assert result.plan is not None and result.plan.steps
    assert result.result_artifact_id == "result-fx-venue-slug"

    # A checkpoint at every stage boundary: seven snapshots, latest pointer set.
    assert store.versions(state.workflow_id) == (1, 2, 3, 4, 5, 6, 7)
    assert state.checkpoints.latest is not None and state.checkpoints.latest.endswith("v0007")

    # Every stage artifact is persisted and referenced.
    for artifact_id in (
        "task-spec-fx-venue-slug",
        "investigation-fx-venue-slug",
        "plan-fx-venue-slug",
        "patch-fx-venue-slug-1",
        "validation-fx-venue-slug-1",
        "result-fx-venue-slug",
    ):
        assert store.has_artifact(state.workflow_id, artifact_id), artifact_id
    assert state.artifacts.plan == "plan-fx-venue-slug"
    assert state.artifacts.patches == ["patch-fx-venue-slug-1"]

    # The engine traces every transition and every checkpoint.
    events = read_trace(trace_path)
    transitions = [
        (e.payload["from"], e.payload["to"])
        for e in events
        if e.event_type == "state_transitioned" and e.component == "workflows"
    ]
    assert transitions == [
        ("intake", "investigate"),
        ("investigate", "plan"),
        ("plan", "plan_approval"),
        ("plan_approval", "implement"),
        ("implement", "validate"),
        ("validate", "prepare_result"),
        ("prepare_result", "completed"),
    ]
    assert sum(1 for e in events if e.event_type == "checkpoint_created") == 7

    # The target itself is untouched: the write ran in a (destroyed) worktree.
    assert _git_status(target) == ""
    assert _no_worktrees_left(target)


def test_plan_rejection_cancels_before_implementation(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    # Deny-by-default gate: the plan approval is rejected; implement must never run.
    result = _engine(target, store, _happy_steps()[:2], gate=ApprovalGate()).run()

    state = result.state
    assert state.status.state is WorkflowStatus.CANCELLED
    assert state.status.current_stage == Stage.CANCELLED.value
    assert state.status.termination_reason == "plan_rejected: rejected"
    assert result.patch is None
    assert [inv.stage for inv in state.workers.invocations] == [Stage.INVESTIGATE.value]
    assert state.approvals.resolved[-1].decision == ApprovalDecision.REJECTED.value
    assert not (target.parent / ".anse-worktrees").exists()
    assert _git_status(target) == ""


def test_failed_validation_cannot_produce_success(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    # The edit introduces trailing whitespace, so the format check fails.
    steps = [
        _happy_steps()[0],
        _happy_steps()[1],
        _edit(new_text=NEW_RETURN + " "),
        _answer("Edited the slug rule."),
    ]
    result = _engine(target, store, steps).run()

    state = result.state
    assert state.status.state is WorkflowStatus.FAILED
    assert state.status.current_stage == Stage.FAILED.value
    assert state.status.termination_reason is not None
    assert state.status.termination_reason.startswith("validation_failed")
    assert result.validation_ok is False
    assert result.patch is None
    assert state.artifacts.patches == []
    assert state.failures.events and state.failures.events[-1].stage == Stage.VALIDATE.value
    # The failed change was rolled back and the worktree destroyed.
    assert _git_status(target) == ""
    assert _no_worktrees_left(target)


def test_rejected_patch_approval_fails_explicitly(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")

    def plan_only(request: ApprovalRequest) -> ApprovalDecision:
        if request.action == "approve_plan":
            return ApprovalDecision.APPROVED
        return ApprovalDecision.REJECTED

    result = _engine(target, store, _happy_steps(), gate=ApprovalGate(plan_only)).run()

    state = result.state
    assert state.status.state is WorkflowStatus.FAILED
    assert state.status.termination_reason is not None
    assert state.status.termination_reason.startswith("patch_approval_rejected")
    assert result.validation_ok is True  # validation passed; the approval did not
    assert result.patch is None
    assert _git_status(target) == ""


def test_cancel_is_an_explicit_terminal(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    engine = _engine(target, store, [])
    engine.cancel("operator request")

    state = engine.state
    assert state.status.state is WorkflowStatus.CANCELLED
    assert state.status.current_stage == Stage.CANCELLED.value
    assert state.status.termination_reason == "cancelled: operator request"
    # The cancellation itself is checkpointed.
    assert store.versions(state.workflow_id) == (1,)

    with pytest.raises(WorkflowError):
        engine.cancel("again")
    with pytest.raises(WorkflowError):
        engine.run()


def test_run_on_a_terminal_workflow_raises(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    engine = _engine(target, store, _happy_steps())
    engine.run()
    with pytest.raises(WorkflowError):
        engine.run()


def test_cost_exhaustion_escalates_the_workflow(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    engine = WorkflowEngine(
        SPEC,
        target,
        _adapter(_happy_steps()),
        store,
        gate=ApprovalGate(approve_all),
        max_cost_usd=0.0000001,  # exhausted by the first investigate call
    )
    result = engine.run()

    state = result.state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.current_stage == Stage.ESCALATED.value
    assert state.status.termination_reason == "investigation cost budget exhausted"
    assert result.patch is None
    with pytest.raises(WorkflowError):
        engine.run()


def test_budgets_and_worker_invocations_are_recorded(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    result = _engine(target, store, _happy_steps()).run()

    budgets = result.state.budgets
    assert budgets.worker_count == 2  # investigator + implementer
    assert budgets.monetary_used > 0.0
    assert budgets.token_used > 0  # the planning call's usage
    invocations = result.state.workers.invocations
    assert [inv.worker_type for inv in invocations] == ["investigator", "implementer"]
    assert [inv.stage for inv in invocations] == [
        Stage.INVESTIGATE.value,
        Stage.IMPLEMENT.value,
    ]
    assert all(inv.status == "completed" for inv in invocations)
