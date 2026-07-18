"""The reliability controller over the UNCHANGED Module 5 engine (Lessons 7.2-7.4).

Retryable failures are retried via resume; non-retryable failures are not blindly
retried; the circuit breaker stops a failing boundary; escalation preserves its
evidence; partial results stay inspectable; resumed workflows do not duplicate
completed actions; and injected store corruption refuses resume LOUDLY. The engine
is driven only through its public run/resume surface. These fail against the
scaffolding stubs and pass once Module 7 is implemented to the reference behaviour.
"""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.models import (
    CostTable,
    ModelAdapter,
    ModelResponse,
    ScriptedAdapter,
    ScriptStep,
    ToolCall,
)
from anse_harness.models.errors import ReplayExhaustedError
from anse_harness.models.types import Usage
from anse_harness.reliability import (
    CircuitBreaker,
    FailureInjectionAdapter,
    InjectionSpec,
    ReliabilityController,
    RetryMode,
    RetryRule,
    aborted_run_artifact_id,
    escalation_artifact_id,
    failure_artifact_id,
    retry_artifact_id,
)
from anse_harness.reliability.injection import corrupt_latest_snapshot
from anse_harness.state.store import WorkflowStateStore
from anse_harness.tracing import TraceWriter, read_trace
from anse_harness.workflows.engine import (
    Stage,
    WorkflowEngine,
    WorkflowError,
    WorkflowResult,
    WorkflowTaskSpec,
)
from anse_harness.workflows.state import StateSchemaError, WorkflowStatus

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m05"
WORKFLOW_ID = "wf-reliability-test"

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

COST = CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)


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


def _answer(text: str) -> ScriptStep:
    return ScriptStep(response=ModelResponse(text=text, usage=Usage(100, 20)))


def _edit_step() -> ScriptStep:
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
                        "new_text": NEW_RETURN,
                    },
                )
            ],
            usage=Usage(100, 30),
            stop_reason="tool_use",
        )
    )


def _full_steps() -> list[ScriptStep]:
    """Investigate, plan, and both implement steps: model calls 1-4."""
    return [
        _answer("The slug rule lives in internal/directory/slug.go and never adds hyphens."),
        _answer("1. Extend the return expression in internal/directory/slug.go."),
        _edit_step(),
        _answer("Extended the slug rule to replace spaces with hyphens, as planned."),
    ]


def _implement_steps() -> list[ScriptStep]:
    """ONLY the implement-stage steps: what a resumed attempt needs."""
    return [_edit_step(), _answer("Extended the slug rule as planned.")]


def _adapter(steps: list[ScriptStep], injection: InjectionSpec | None) -> ModelAdapter:
    return FailureInjectionAdapter(ScriptedAdapter(steps, cost_table=COST), injection)


def _engine(
    target: Path,
    store: WorkflowStateStore,
    adapter: ModelAdapter,
    *,
    tracer: TraceWriter | None = None,
) -> WorkflowEngine:
    return WorkflowEngine(
        SPEC,
        target,
        adapter,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id=WORKFLOW_ID,
        max_cost_usd=1.0,
        tracer=tracer,
    )


def _resumed(
    target: Path,
    store: WorkflowStateStore,
    adapter: ModelAdapter,
    *,
    tracer: TraceWriter | None = None,
) -> WorkflowEngine:
    return WorkflowEngine.resume(
        store,
        WORKFLOW_ID,
        spec=SPEC,
        target_root=target,
        adapter=adapter,
        gate=ApprovalGate(approve_all),
        max_cost_usd=1.0,
        tracer=tracer,
    )


#: The recovery attempt factory most tests use: attempt 1 runs the full script
#: under the injection; later attempts resume with a continuation adapter.
def _attempts(
    target: Path,
    store: WorkflowStateStore,
    *,
    first_injection: InjectionSpec | None,
    later_injection: InjectionSpec | None = None,
    tracers: dict[int, TraceWriter] | None = None,
) -> Callable[[int], WorkflowResult]:
    def attempts(n: int) -> WorkflowResult:
        tracer = tracers.get(n) if tracers is not None else None
        if n == 1:
            return _engine(
                target, store, _adapter(_full_steps(), first_injection), tracer=tracer
            ).run()
        return _resumed(
            target, store, _adapter(_implement_steps(), later_injection), tracer=tracer
        ).run()

    return attempts


def _artifact_ids(tmp_path: Path) -> list[str]:
    return sorted(p.stem for p in (tmp_path / "state" / WORKFLOW_ID / "artifacts").glob("*.json"))


TIMEOUT_AT_IMPLEMENT = InjectionSpec(at_call=3, failure="model_timeout")


def test_retryable_failure_is_retried_via_resume_to_completion(
    target: Path, tmp_path: Path
) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    controller_trace = tmp_path / "controller.jsonl"
    with TraceWriter(controller_trace) as writer:
        controller = ReliabilityController(store, WORKFLOW_ID, tracer=writer)
        outcome = controller.execute(
            _attempts(target, store, first_injection=TIMEOUT_AT_IMPLEMENT),
            target_root=target,
        )

    assert outcome.escalated is False
    assert outcome.attempts == 2
    assert outcome.result is not None
    state = outcome.result.state
    assert state.status.state is WorkflowStatus.COMPLETED
    # Reliability bookkeeping lives in the UNCHANGED schema.
    assert state.budgets.retry_count == 1
    assert len(state.failures.events) == 1
    event = state.failures.events[0]
    assert event.stage == Stage.IMPLEMENT.value
    assert event.reason.startswith("model-provider failure at the model boundary:")
    # One explicit retry decision, in order.
    assert [decision.action for decision in outcome.decisions] == ["retry"]
    assert outcome.decisions[0].mode is RetryMode.SAME_INPUT
    # The failure classification and the retry decision are persisted artifacts.
    assert store.has_artifact(WORKFLOW_ID, failure_artifact_id(SPEC.task_id, 1))
    assert store.has_artifact(WORKFLOW_ID, retry_artifact_id(SPEC.task_id, 1))
    record = store.load_artifact(WORKFLOW_ID, failure_artifact_id(SPEC.task_id, 1))
    assert record["classification"]["failure_class"] == "model-provider failure"
    assert record["classification"]["boundary"] == "model"
    # retry_scheduled went through the closed event vocabulary with the canonical
    # class and the arch-ref 51 mode in its payload.
    events = list(read_trace(controller_trace))
    scheduled = [e for e in events if e.event_type == "retry_scheduled"]
    assert len(scheduled) == 1
    assert scheduled[0].payload["failure_class"] == "model-provider failure"
    assert scheduled[0].payload["retry_mode"] == "same-input retry"
    assert scheduled[0].payload["failed_attempt"] == 1
    assert scheduled[0].payload["next_attempt"] == 2


def test_recovered_run_matches_a_clean_run_without_duplicated_actions(
    target: Path, tmp_path: Path
) -> None:
    # Clean run in its own environment.
    clean_target = tmp_path / "clean-target"
    shutil.copytree(target, clean_target)
    clean_store = WorkflowStateStore(tmp_path / "clean-state")
    clean_result = _engine(clean_target, clean_store, _adapter(_full_steps(), None)).run()
    assert clean_result.state.status.state is WorkflowStatus.COMPLETED

    # Injected failure + controller recovery over the same fixture.
    store = WorkflowStateStore(tmp_path / "state")
    controller = ReliabilityController(store, WORKFLOW_ID)
    outcome = controller.execute(
        _attempts(target, store, first_injection=TIMEOUT_AT_IMPLEMENT),
        target_root=target,
    )
    assert outcome.result is not None

    # The patch is byte-identical: the retry did not duplicate or alter the work.
    assert outcome.result.patch == clean_result.patch
    # Exactly ONE patch artifact exists after recovery - no duplicated action.
    artifacts = _artifact_ids(tmp_path)
    assert [a for a in artifacts if a.startswith("patch-")] == ["patch-fx-venue-slug-1"]
    # Budgets agree except for the retry bookkeeping (and wall-clock).
    clean_budgets = clean_result.state.to_payload()["budgets"]
    recovered_budgets = outcome.result.state.to_payload()["budgets"]
    for payload in (clean_budgets, recovered_budgets):
        payload.pop("elapsed_seconds")
    assert recovered_budgets.pop("retry_count") == 1
    assert clean_budgets.pop("retry_count") == 0
    assert recovered_budgets == clean_budgets


def test_non_retryable_failure_is_not_blindly_retried(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    controller = ReliabilityController(store, WORKFLOW_ID)
    outcome = controller.execute(
        _attempts(
            target,
            store,
            first_injection=InjectionSpec(at_call=3, failure="provider_error_permanent"),
        ),
        target_root=target,
    )
    # ONE attempt only: a permanent provider error is never same-input retried.
    assert outcome.attempts == 1
    assert outcome.escalated is True
    assert outcome.result is None
    assert [decision.action for decision in outcome.decisions] == ["escalate"]
    state = store.load_latest(WORKFLOW_ID).state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.termination_reason == (
        "non-retryable failure: a same-input retry would reproduce it"
    )
    assert state.budgets.retry_count == 0


def test_circuit_breaker_opens_and_short_circuits_to_escalation(
    target: Path, tmp_path: Path
) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    # A generous retry budget: the BREAKER must be what stops the run.
    policy = {"model-provider failure": RetryRule(RetryMode.SAME_INPUT, 10)}
    controller = ReliabilityController(
        store, WORKFLOW_ID, policy=policy, breaker=CircuitBreaker(threshold=2)
    )
    outcome = controller.execute(
        _attempts(
            target,
            store,
            first_injection=TIMEOUT_AT_IMPLEMENT,
            later_injection=InjectionSpec(at_call=1, failure="model_timeout"),
        ),
        target_root=target,
    )
    assert outcome.attempts == 2
    assert outcome.escalated is True
    state = store.load_latest(WORKFLOW_ID).state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.termination_reason == (
        "circuit breaker open: 2 consecutive failures at the model boundary"
    )
    # Every observed failure is in the history; one retry was actually performed.
    assert len(state.failures.events) == 2
    assert state.budgets.retry_count == 1
    # The terminal refuses resume - the breaker's stop is a real terminal.
    with pytest.raises(WorkflowError, match="terminal"):
        _resumed(target, store, _adapter(_implement_steps(), None))


def test_escalation_preserves_evidence(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    attempt_traces = {1: tmp_path / "attempt1.jsonl", 2: tmp_path / "attempt2.jsonl"}
    policy = {"model-provider failure": RetryRule(RetryMode.SAME_INPUT, 2)}
    with (
        TraceWriter(attempt_traces[1]) as first,
        TraceWriter(attempt_traces[2]) as second,
    ):
        controller = ReliabilityController(store, WORKFLOW_ID, policy=policy)
        outcome = controller.execute(
            _attempts(
                target,
                store,
                first_injection=TIMEOUT_AT_IMPLEMENT,
                later_injection=InjectionSpec(at_call=1, failure="model_timeout"),
                tracers={1: first, 2: second},
            ),
            target_root=target,
            attempt_trace=lambda n: attempt_traces[n],
        )
    assert outcome.escalated is True

    request = store.load_artifact(WORKFLOW_ID, escalation_artifact_id(SPEC.task_id))
    state = store.load_latest(WORKFLOW_ID).state
    # The failure history is complete and canonical.
    assert request["failure_history"] == [event.reason for event in state.failures.events]
    assert len(request["failure_history"]) == 2
    # Every referenced evidence artifact is actually present in the store.
    assert request["evidence_artifacts"]
    for artifact_id in request["evidence_artifacts"]:
        assert store.has_artifact(WORKFLOW_ID, artifact_id), artifact_id
    # The classification and decision records are part of the evidence.
    assert failure_artifact_id(SPEC.task_id, 1) in request["evidence_artifacts"]
    assert retry_artifact_id(SPEC.task_id, 2) in request["evidence_artifacts"]
    # The attempts' trace files are named (names, never machine paths).
    assert request["trace_files"] == ["attempt1.jsonl", "attempt2.jsonl"]
    assert request["artifact"] == aborted_run_artifact_id(SPEC.task_id)
    assert request["revision"]
    assert request["repository"] == "target"


def test_partial_results_remain_inspectable_after_abort(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    attempt_traces = {1: tmp_path / "attempt1.jsonl"}
    with TraceWriter(attempt_traces[1]) as writer:
        controller = ReliabilityController(store, WORKFLOW_ID)
        # The crash happens AFTER the implement stage's first model call, so the
        # attempt has real spend the workflow budgets never saw (the stage never
        # completed, so its cost never folded in).
        outcome = controller.execute(
            _attempts(
                target,
                store,
                first_injection=InjectionSpec(at_call=4, failure="provider_error_permanent"),
                tracers={1: writer},
            ),
            target_root=target,
            attempt_trace=lambda n: attempt_traces[n],
        )
    assert outcome.escalated is True

    report = store.load_artifact(WORKFLOW_ID, aborted_run_artifact_id(SPEC.task_id))
    # The surviving artifacts - the work completed BEFORE the failure - are listed
    # and every one of them is loadable: partial results stay inspectable.
    surviving = report["surviving_artifacts"]
    assert "task-spec-fx-venue-slug" in surviving
    assert "plan-fx-venue-slug" in surviving
    for artifact_id in surviving:
        assert store.load_artifact(WORKFLOW_ID, artifact_id)
    # The crashed stage's model spend is NOT in the budgets - the report carries
    # it explicitly instead of pretending it does not exist: unaccounted spend =
    # the attempt's observed cost minus what the budgets accounted for.
    observed = outcome.decisions[0].observed_attempt_cost_usd
    assert observed is not None
    unaccounted = report["unaccounted_attempt_cost_usd"]
    assert unaccounted > 0
    assert unaccounted == round(observed - report["budgets"]["monetary_used"], 10)
    assert report["termination_reason"] == (
        "non-retryable failure: a same-input retry would reproduce it"
    )


def test_engine_handled_failure_is_classified_not_crashed_and_not_retried(
    target: Path, tmp_path: Path
) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    # Malformed structured output: the plan reply carries no usable steps. The
    # ENGINE handles it (failed terminal); the controller classifies the outcome.
    steps = [
        _answer("The slug rule lives in internal/directory/slug.go."),
        _answer(""),
    ]

    def attempts(n: int) -> WorkflowResult:
        return _engine(target, store, _adapter(steps, None)).run()

    controller = ReliabilityController(store, WORKFLOW_ID)
    outcome = controller.execute(attempts, target_root=target)
    assert outcome.attempts == 1
    assert outcome.decisions == ()
    assert outcome.result is not None
    assert outcome.result.state.status.state is WorkflowStatus.FAILED
    record = store.load_artifact(WORKFLOW_ID, failure_artifact_id(SPEC.task_id, 1))
    assert record["classification"]["failure_class"] == "malformed output"
    assert record["classification"]["boundary"] == "model"


def test_corrupted_checkpoint_refuses_resume_loudly(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    result = _engine(target, store, _adapter(_full_steps(), None)).run(
        stop_after=Stage.PLAN_APPROVAL
    )
    assert result.state.status.state is WorkflowStatus.RUNNING
    corrupt_latest_snapshot(tmp_path / "state", WORKFLOW_ID)
    with pytest.raises(StateSchemaError, match="refusing to load"):
        _resumed(target, store, _adapter(_implement_steps(), None))


def test_missing_referenced_artifact_refuses_resume(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    _engine(target, store, _adapter(_full_steps(), None)).run(stop_after=Stage.PLAN_APPROVAL)
    plan_artifact = tmp_path / "state" / WORKFLOW_ID / "artifacts" / "plan-fx-venue-slug.json"
    plan_artifact.unlink()
    with pytest.raises(WorkflowError, match="refusing to resume"):
        _resumed(target, store, _adapter(_implement_steps(), None))


def test_replay_discipline_errors_are_reraised_not_escalated(target: Path, tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path / "state")
    controller = ReliabilityController(store, WORKFLOW_ID)

    def attempts(n: int) -> WorkflowResult:
        raise ReplayExhaustedError("the trace holds no further model interactions")

    # A replay-discipline violation is NOT a workflow failure: no classification,
    # no retry, no escalation - the error stays loud.
    with pytest.raises(ReplayExhaustedError):
        controller.execute(attempts, target_root=target)
    assert store.versions(WORKFLOW_ID) == ()
