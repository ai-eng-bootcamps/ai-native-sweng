"""Replay conformance for the Module 7 reliability trace sets.

Two committed stories, both replayed at zero model cost:

* ``traces/m07/recovery`` - a Module 5 workflow crashes on an INJECTED provider
  timeout at overall model call 6 and is resumed to completion by the reliability
  controller. The layout is one file PER ATTEMPT plus the controller's own file
  (never append a resumed run to an existing file - engine event ids restart per
  instance). Attempt 1 was recorded under a raise-level ``InjectionSpec``; the
  spec is COMMITTED beside the trace (``attempt1.injection.json``) and is REQUIRED
  replay configuration: the same wrapper that injected the failure at record time
  re-applies it at the identical call over the ReplayAdapter. Replaying attempt 1
  WITHOUT the spec fails loudly - the trace carries six requests but five
  responses. That is the honest boundary of replay: recorded model interactions
  replay byte-exactly; injected provider raises are re-applied by configuration,
  and the configuration ships with the trace.
* ``traces/m07/escalation`` - the Module 6 multi-worker run whose fix worker
  changes nothing and whose re-review repeats its finding (script-channel
  injection only, so it replays with no extra configuration): the loop detects no
  progress and escalates with the residual finding preserved.

The fixture repositories, identity, and clock are pinned exactly as in Modules
3-6 and must stay in lockstep with the reference trace-generation entry point.
These fail against the scaffolding stubs and pass once Modules 5-7 are
implemented to the reference behaviour.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.budgets.policy import TerminationPolicy
from anse_harness.models import CostTable, ModelAdapter, ReplayAdapter
from anse_harness.models.errors import ReplayExhaustedError
from anse_harness.reliability import (
    FailureInjectionAdapter,
    InjectionSpec,
    ReliabilityController,
)
from anse_harness.state.store import WorkflowStateStore
from anse_harness.tracing import TraceWriter, read_trace
from anse_harness.workflows.engine import (
    WorkflowEngine,
    WorkflowResult,
    WorkflowTaskSpec,
)
from anse_harness.workflows.graph import TaskGraph
from anse_harness.workflows.orchestrator import (
    MultiWorkerOrchestrator,
    MultiWorkerSpec,
    ReviewerSpec,
    worker_trace_filename,
)
from anse_harness.workflows.state import WorkflowStatus

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TRACES = Path(__file__).resolve().parents[2] / "traces" / "m07"
COST_TABLE = CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)

#: Pinned identity and date, so the materialized fixture repositories have the same
#: base revision on every machine. Must match the reference trace-generation entry
#: point.
PINNED_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "ANSE Course",
    "GIT_AUTHOR_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_NAME": "ANSE Course",
    "GIT_COMMITTER_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

#: Pinned clock for the recorded runs. Must match the reference entry point.
PINNED_CLOCK_ISO = "2026-01-01T00:00:00+00:00"

RECOVERY_WORKFLOW_ID = "wf-m07-recovery"
ESCALATION_WORKFLOW_ID = "wf-m07-escalation"

#: The complete escalation set: one file per worker invocation plus the
#: orchestrator (the fix round and the repeated re-review included).
ESCALATION_TRACE_FILES = {
    "worker_a.jsonl",
    "worker_b.jsonl",
    "worker_c.jsonl",
    "reviewer_1.jsonl",
    "reviewer_2.jsonl",
    "reviewer_3.jsonl",
    "fixer_1.jsonl",
    "reviewer_1_round_2.jsonl",
}


def _materialize(fixture_tree: Path, tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(fixture_tree, repo)
    env = {**os.environ, **PINNED_COMMIT_ENV}
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "-c", "core.autocrlf=false", "add", "-A"],
        ["git", "commit", "-q", "-m", "Practice fixture baseline"],
    ):
        subprocess.run(args, cwd=repo, env=env, check=True, capture_output=True)
    return repo


def _workflow_spec() -> WorkflowTaskSpec:
    raw = json.loads((FIXTURES / "m05" / "workflow_task.json").read_text(encoding="utf-8"))
    return WorkflowTaskSpec(
        task_id=raw["task_id"],
        description=raw["description"],
        acceptance_criteria=tuple(raw["acceptance_criteria"]),
        worker_type=raw["worker_type"],
        token_budget=raw["token_budget"],
        search_terms=tuple(raw["search_terms"]),
        conflict_topics=tuple(raw.get("conflict_topics", [])),
    )


def _recovery_attempts(
    repo: Path, store: WorkflowStateStore, injection: InjectionSpec | None
) -> Callable[[int], WorkflowResult]:
    """Attempt factory over the committed per-attempt replay files."""

    def attempts(n: int) -> WorkflowResult:
        adapter: ModelAdapter = ReplayAdapter(TRACES / "recovery" / f"attempt{n}.jsonl", COST_TABLE)
        if n == 1 and injection is not None:
            adapter = FailureInjectionAdapter(adapter, injection)
        if n == 1:
            engine = WorkflowEngine(
                _workflow_spec(),
                repo,
                adapter,
                store,
                gate=ApprovalGate(approve_all),
                workflow_id=RECOVERY_WORKFLOW_ID,
                max_cost_usd=1.0,
                clock=lambda: PINNED_CLOCK_ISO,
            )
        else:
            engine = WorkflowEngine.resume(
                store,
                RECOVERY_WORKFLOW_ID,
                spec=_workflow_spec(),
                target_root=repo,
                adapter=adapter,
                gate=ApprovalGate(approve_all),
                max_cost_usd=1.0,
                clock=lambda: PINNED_CLOCK_ISO,
            )
        return engine.run()

    return attempts


def test_recovery_set_replays_byte_exactly_with_its_committed_injection_spec(
    tmp_path: Path,
) -> None:
    repo = _materialize(FIXTURES / "m05" / "repo", tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: PINNED_CLOCK_ISO)
    injection = InjectionSpec.from_file(TRACES / "recovery" / "attempt1.injection.json")
    controller_trace = tmp_path / "controller.jsonl"

    with TraceWriter(controller_trace) as writer:
        controller = ReliabilityController(store, RECOVERY_WORKFLOW_ID, tracer=writer)
        outcome = controller.execute(
            _recovery_attempts(repo, store, injection),
            target_root=repo,
            attempt_trace=lambda n: TRACES / "recovery" / f"attempt{n}.jsonl",
        )

    # The whole story replays: crash at the injected call, one scheduled retry,
    # resumed completion - with zero replay mismatches.
    assert outcome.escalated is False
    assert outcome.attempts == 2
    assert outcome.result is not None
    state = outcome.result.state
    assert state.status.state is WorkflowStatus.COMPLETED
    assert state.budgets.retry_count == 1
    assert len(state.failures.events) == 1
    assert state.failures.events[0].reason.startswith(
        "model-provider failure at the model boundary:"
    )

    # The replayed patch is byte-identical to the recorded one (the result
    # artifact event in attempt 2's trace carries the recorded bytes).
    recorded_result = next(
        event.payload
        for event in read_trace(TRACES / "recovery" / "attempt2.jsonl")
        if event.event_type == "artifact_created" and event.payload.get("artifact_type") == "result"
    )
    assert outcome.result.patch is not None
    assert outcome.result.patch == recorded_result["patch"]

    # The controller's replayed decisions reproduce the committed controller
    # trace: same event ids, same types, same payloads (including the observed
    # attempt cost read from the committed attempt trace).
    recorded = [
        (event.event_id, event.event_type, event.payload)
        for event in read_trace(TRACES / "recovery" / "controller.jsonl")
    ]
    replayed = [
        (event.event_id, event.event_type, event.payload) for event in read_trace(controller_trace)
    ]
    assert replayed == recorded
    assert [event_type for _, event_type, _ in recorded] == [
        "artifact_created",
        "artifact_created",
        "checkpoint_created",
        "retry_scheduled",
    ]

    # Attempt 1's committed trace really is the interrupted shape: one more
    # request than responses (the injected call), in its OWN file.
    census: dict[str, int] = {}
    for event in read_trace(TRACES / "recovery" / "attempt1.jsonl"):
        census[event.event_type] = census.get(event.event_type, 0) + 1
    assert census["model_requested"] == 6
    assert census["model_responded"] == 5


def test_raise_injected_trace_without_its_spec_fails_loudly(tmp_path: Path) -> None:
    repo = _materialize(FIXTURES / "m05" / "repo", tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: PINNED_CLOCK_ISO)
    controller = ReliabilityController(store, RECOVERY_WORKFLOW_ID)
    # The injection spec is replay CONFIGURATION, not decoration: without it the
    # sixth request exhausts the five recorded responses and replay fails LOUDLY
    # (re-raised through the controller, never classified or escalated).
    with pytest.raises(ReplayExhaustedError):
        controller.execute(_recovery_attempts(repo, store, None), target_root=repo)


def test_escalation_set_replays_to_the_recorded_no_progress_stop(
    tmp_path: Path,
) -> None:
    repo = _materialize(FIXTURES / "m06" / "repo", tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: PINNED_CLOCK_ISO)
    raw = json.loads((FIXTURES / "m06" / "multiworker_task.json").read_text(encoding="utf-8"))
    spec = MultiWorkerSpec(
        task_id=raw["task_id"],
        description=raw["description"],
        acceptance_criteria=tuple(raw["acceptance_criteria"]),
        graph=TaskGraph.from_payload(raw["graph"]),
        reviewers=tuple(
            ReviewerSpec(reviewer_id=item["reviewer_id"], concern=item["concern"])
            for item in raw["reviewers"]
        ),
        token_budget=raw["token_budget"],
    )
    replayed_files: list[str] = []

    def adapters(worker_id: str, stage: str, attempt: int) -> ModelAdapter:
        name = worker_trace_filename(worker_id, attempt)
        replayed_files.append(name)
        return ReplayAdapter(TRACES / "escalation" / name, COST_TABLE)

    orchestrator = MultiWorkerOrchestrator(
        spec,
        repo,
        adapters,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id=ESCALATION_WORKFLOW_ID,
        max_concurrency=1,
        termination=TerminationPolicy(max_review_iterations=3),
        clock=lambda: PINNED_CLOCK_ISO,
    )
    result = orchestrator.run()

    state = result.state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.termination_reason is not None
    assert "no progress" in state.status.termination_reason
    assert result.review_iterations == 2
    # Every file of the committed set drove exactly one worker's replay.
    assert set(replayed_files) == ESCALATION_TRACE_FILES
    assert len(replayed_files) == len(ESCALATION_TRACE_FILES)

    # The recorded orchestrator trace matches the replayed run structurally: the
    # loop went fix -> validate -> review -> consolidate and STOPPED there.
    orchestrator_events = read_trace(TRACES / "escalation" / "orchestrator.jsonl")
    recorded_transitions = [
        (event.payload["from"], event.payload["to"])
        for event in orchestrator_events
        if event.event_type == "state_transitioned"
    ]
    assert recorded_transitions == [
        ("intake", "fan_out"),
        ("fan_out", "integrate"),
        ("integrate", "validate"),
        ("validate", "review"),
        ("review", "consolidate"),
        ("consolidate", "fix"),
        ("fix", "validate"),
        ("validate", "review"),
        ("review", "consolidate"),
        ("consolidate", "escalated"),
    ]
    escalations = [
        event for event in orchestrator_events if event.event_type == "escalation_created"
    ]
    assert len(escalations) == 1
    assert "no progress" in escalations[0].payload["reason"]
    # The residual finding survived to the terminal state: escalation preserved
    # the evidence the human needs.
    assert state.artifacts.consolidated_review is not None
    consolidated = store.load_artifact(ESCALATION_WORKFLOW_ID, state.artifacts.consolidated_review)
    assert consolidated["accepted"]
    assert consolidated["accepted"][0]["deduplication_key"] == "tags-normalize-trailing-whitespace"
