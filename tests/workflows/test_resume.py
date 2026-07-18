"""Persistence, resume, and cancellation of the stateful workflow (Lesson 5.5).

An interrupted workflow (deterministically stopped at a stage boundary, leaving
exactly what a killed process would leave on disk) resumes from its latest checkpoint
and completes WITHOUT re-running earlier stages; resume verifies the schema version,
the task, the repository revision, and artifact availability before anything runs.
These fail against the scaffolding stubs and pass once the store and the engine are
implemented to the reference behaviour.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.models import CostTable, ModelResponse, ScriptedAdapter, ScriptStep, ToolCall
from anse_harness.models.errors import ScriptExhaustedError
from anse_harness.models.types import Usage
from anse_harness.state.store import StateStoreError, WorkflowStateStore
from anse_harness.workflows.engine import (
    Stage,
    WorkflowEngine,
    WorkflowError,
    WorkflowTaskSpec,
)
from anse_harness.workflows.state import StateSchemaError, WorkflowStatus

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m05"
WORKFLOW_ID = "wf-resume-test"

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
    repo = tmp_path / "target"
    shutil.copytree(FIXTURES / "repo", repo)
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "base"],
    ):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)
    return repo


def _adapter(steps: list[ScriptStep]) -> ScriptedAdapter:
    return ScriptedAdapter(
        steps, cost_table=CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)
    )


def _answer(text: str) -> ScriptStep:
    return ScriptStep(response=ModelResponse(text=text, usage=Usage(100, 20)))


def _pre_interrupt_steps() -> list[ScriptStep]:
    """The model steps up to and including planning (investigate + plan)."""
    return [
        _answer("The slug rule lives in internal/directory/slug.go and never adds hyphens."),
        _answer("1. Extend the return expression in internal/directory/slug.go."),
    ]


def _post_interrupt_steps() -> list[ScriptStep]:
    """ONLY the implementation steps: a resumed run must not re-run earlier stages."""
    return [
        ScriptStep(
            response=ModelResponse(
                text="Editing the slug rule.",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="replace_text",
                        arguments={
                            "path": "internal/directory/slug.go",
                            "old_text": OLD_RETURN,
                            "new_text": NEW_RETURN,
                        },
                    )
                ],
                usage=Usage(100, 30),
                stop_reason="tool_use",
            )
        ),
        _answer("Extended the slug rule to replace spaces with hyphens, as planned."),
    ]


def _interrupted_store(target: Path, tmp_path: Path) -> WorkflowStateStore:
    """Run up to the plan-approval boundary, then 'die': four snapshots on disk."""
    store = WorkflowStateStore(tmp_path / "state")
    engine = WorkflowEngine(
        SPEC,
        target,
        _adapter(_pre_interrupt_steps()),
        store,
        gate=ApprovalGate(approve_all),
        workflow_id=WORKFLOW_ID,
        max_cost_usd=1.0,
    )
    result = engine.run(stop_after=Stage.PLAN_APPROVAL)
    assert result.state.status.state is WorkflowStatus.RUNNING
    assert result.state.status.current_stage == Stage.IMPLEMENT.value
    assert store.versions(WORKFLOW_ID) == (1, 2, 3, 4)
    return store


def _resume(
    store: WorkflowStateStore,
    target: Path,
    steps: list[ScriptStep],
    *,
    spec: WorkflowTaskSpec = SPEC,
) -> WorkflowEngine:
    return WorkflowEngine.resume(
        store,
        WORKFLOW_ID,
        spec=spec,
        target_root=target,
        adapter=_adapter(steps),
        gate=ApprovalGate(approve_all),
        max_cost_usd=1.0,
    )


def test_resume_completes_without_rerunning_earlier_stages(target: Path, tmp_path: Path) -> None:
    store = _interrupted_store(target, tmp_path)

    # The resumed adapter carries ONLY the implementation steps: if the engine
    # re-ran investigation or planning, the script would mismatch or exhaust.
    engine = _resume(store, target, _post_interrupt_steps())
    result = engine.run()

    state = result.state
    assert state.status.state is WorkflowStatus.COMPLETED
    assert state.status.termination_reason == "completed"
    assert result.patch is not None and "ReplaceAll" in result.patch
    assert result.validation_ok is True
    # The plan came back from the artifact store, not from a re-run.
    assert result.plan is not None and result.plan.plan_id == "plan-fx-venue-slug"
    # Snapshots continue the persisted numbering (implement, validate, prepare_result).
    assert store.versions(WORKFLOW_ID) == (1, 2, 3, 4, 5, 6, 7)
    # The resume itself is recorded as an artifact.
    assert store.has_artifact(WORKFLOW_ID, "resume-fx-venue-slug-v0004")


def test_resume_verifies_the_repository_revision(target: Path, tmp_path: Path) -> None:
    store = _interrupted_store(target, tmp_path)
    (target / "NEW.md").write_text("moved\n", encoding="utf-8")
    for args in (
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "m"],
    ):
        subprocess.run(args, cwd=target, check=True, capture_output=True)
    with pytest.raises(WorkflowError, match="refusing to resume"):
        _resume(store, target, _post_interrupt_steps())


def test_resume_fails_loudly_on_schema_version_drift(target: Path, tmp_path: Path) -> None:
    store = _interrupted_store(target, tmp_path)
    latest = tmp_path / "state" / WORKFLOW_ID / "snapshots" / "state-v0004.json"
    data = json.loads(latest.read_text(encoding="utf-8"))
    data["state"]["schema_version"] = "999"
    latest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StateSchemaError):
        _resume(store, target, _post_interrupt_steps())


def test_resume_verifies_artifact_availability(target: Path, tmp_path: Path) -> None:
    store = _interrupted_store(target, tmp_path)
    (tmp_path / "state" / WORKFLOW_ID / "artifacts" / "plan-fx-venue-slug.json").unlink()
    with pytest.raises(WorkflowError, match="artifact"):
        _resume(store, target, _post_interrupt_steps())


def test_resume_rejects_a_mismatched_task(target: Path, tmp_path: Path) -> None:
    store = _interrupted_store(target, tmp_path)
    other = WorkflowTaskSpec(
        task_id="fx-other-task",
        description="Another task entirely.",
        acceptance_criteria=("It is done.",),
    )
    with pytest.raises(WorkflowError, match="task"):
        _resume(store, target, _post_interrupt_steps(), spec=other)


def test_resume_refuses_a_terminal_workflow(target: Path, tmp_path: Path) -> None:
    store = _interrupted_store(target, tmp_path)
    engine = _resume(store, target, _post_interrupt_steps())
    engine.run()
    with pytest.raises(WorkflowError, match="terminal"):
        _resume(store, target, [])


def test_resume_refuses_an_unknown_workflow(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    with pytest.raises(StateStoreError):
        _resume(store, target, [])


def test_cancelled_workflow_cannot_be_resumed(target: Path, tmp_path: Path) -> None:
    store = _interrupted_store(target, tmp_path)
    engine = _resume(store, target, [])
    engine.cancel("operator request")
    assert store.versions(WORKFLOW_ID) == (1, 2, 3, 4, 5)
    with pytest.raises(WorkflowError, match="terminal"):
        _resume(store, target, [])


def test_interrupted_run_reports_a_partial_result(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    engine = WorkflowEngine(
        SPEC,
        target,
        _adapter(_pre_interrupt_steps()),
        store,
        gate=ApprovalGate(approve_all),
        workflow_id=WORKFLOW_ID,
        max_cost_usd=1.0,
    )
    result = engine.run(stop_after=Stage.INVESTIGATE)
    assert result.state.status.state is WorkflowStatus.RUNNING
    assert result.state.status.current_stage == Stage.PLAN.value
    assert result.investigation_answer is not None
    assert result.plan is None and result.patch is None
    # Nothing after the boundary ran: the plan step is still unconsumed.
    with pytest.raises(ScriptExhaustedError):
        # Only the investigate step was scripted as consumed; re-running from the
        # boundary with an exhausted script proves no hidden extra model calls ran.
        WorkflowEngine.resume(
            store,
            WORKFLOW_ID,
            spec=SPEC,
            target_root=target,
            adapter=ScriptedAdapter([]),
            gate=ApprovalGate(approve_all),
        ).run()
