"""The multi-worker orchestrator end to end (Module 6, Lessons 6.3-6.9).

Exercises the full scripted multi-worker workflow over the Module 6 fixture: fan-out
in graph order under a concurrency bound, deterministic graph-order fan-in,
integration with overlap handling, integrated validation, fresh reviewers,
consolidation, fix workers, targeted re-review, and deterministic loop termination -
plus the failure modes: prohibited overlap, integration conflict, termination at the
iteration limit, no-progress detection, and explicit cancellation. These fail against
the scaffolding stubs and pass once the orchestrator is implemented to the reference
behaviour.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.budgets.policy import TerminationPolicy
from anse_harness.models import (
    CostTable,
    ModelAdapter,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ScriptedAdapter,
    ScriptStep,
)
from anse_harness.models.types import response_from_payload
from anse_harness.state.store import WorkflowStateStore
from anse_harness.workflows.graph import TaskGraph, TaskNode
from anse_harness.workflows.integration import OverlapPolicy
from anse_harness.workflows.orchestrator import (
    MultiWorkerOrchestrator,
    MultiWorkerSpec,
    MultiWorkflowError,
    ReviewerSpec,
    worker_trace_filename,
)
from anse_harness.workflows.state import WorkflowStatus

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m06"
COST_TABLE = CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)
CLOCK = "2026-01-01T00:00:00+00:00"

PINNED_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "ANSE Course",
    "GIT_AUTHOR_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_NAME": "ANSE Course",
    "GIT_COMMITTER_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

#: The canonical invocation order of the recorded demo: fan-out in graph order,
#: reviewers in specification order, one fixer, then the targeted re-review.
EXPECTED_INVOCATION_RUN_IDS = [
    "run-wf-t-worker-a-implement-1",
    "run-wf-t-worker-b-implement-1",
    "run-wf-t-worker-c-implement-1",
    "run-wf-t-reviewer-1-review-1",
    "run-wf-t-reviewer-2-review-1",
    "run-wf-t-reviewer-3-review-1",
    "run-wf-t-fixer-1-fix-1",
    "run-wf-t-reviewer-1-review-2",
]


def _materialize_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "repo", repo)
    env = {**os.environ, **PINNED_COMMIT_ENV}
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "-c", "core.autocrlf=false", "add", "-A"],
        ["git", "commit", "-q", "-m", "Practice fixture baseline"],
    ):
        subprocess.run(args, cwd=repo, env=env, check=True, capture_output=True)
    return repo


def _load_spec() -> MultiWorkerSpec:
    raw = json.loads((FIXTURES / "multiworker_task.json").read_text(encoding="utf-8"))
    return MultiWorkerSpec(
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


class _ScriptFactory:
    """Adapter factory over the fixture scripts; records every requested key."""

    def __init__(self, overrides: dict[tuple[str, str, int], list[ScriptStep]] | None = None):
        self.requested: list[tuple[str, str, int]] = []
        self._overrides = overrides or {}

    def __call__(self, worker_id: str, stage: str, attempt: int) -> ModelAdapter:
        key = (worker_id, stage, attempt)
        self.requested.append(key)
        if key in self._overrides:
            return ScriptedAdapter(list(self._overrides[key]), COST_TABLE)
        stem = worker_trace_filename(worker_id, attempt).removesuffix(".jsonl")
        return ScriptedAdapter.from_file(
            FIXTURES / "scripts" / f"{stem}.script.json", cost_table=COST_TABLE
        )


def _step(text: str, tool_calls: list[dict[str, object]] | None = None) -> ScriptStep:
    return ScriptStep(
        response=response_from_payload(
            {
                "text": text,
                "tool_calls": tool_calls or [],
                "structured_output": None,
                "usage": {"input_tokens": 1000, "output_tokens": 40},
                "stop_reason": "tool_use" if tool_calls else "end_turn",
            }
        )
    )


def _orchestrator(
    repo: Path,
    store: WorkflowStateStore,
    factory: _ScriptFactory,
    **kwargs: object,
) -> MultiWorkerOrchestrator:
    return MultiWorkerOrchestrator(
        _load_spec(),
        repo,
        factory,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id="wf-t",
        clock=lambda: CLOCK,
        **kwargs,  # type: ignore[arg-type]
    )


def _clean(repo: Path) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    )
    worktrees = repo.parent / ".anse-worktrees"
    return status.stdout.strip() == "" and (not worktrees.exists() or not any(worktrees.iterdir()))


def test_full_multiworker_run_completes_through_the_review_fix_loop(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    factory = _ScriptFactory()
    result = _orchestrator(repo, store, factory).run()

    state = result.state
    assert state.status.state is WorkflowStatus.COMPLETED
    assert state.status.termination_reason == "completed"
    assert result.graph_order == ("worker-a", "worker-b", "worker-c")
    assert result.review_iterations == 2
    assert result.validation_ok is True

    # The integrated patch carries all three sub-tasks WITH the fix applied.
    assert result.integrated_patch is not None
    assert "TrimSpace" in result.integrated_patch
    assert "TrimLeft" not in result.integrated_patch
    assert '"<" + label + ">"' in result.integrated_patch
    assert '"tag:" + label' in result.integrated_patch
    # The pre-fix defect is visible in the worker patch, so the loop provably fixed it.
    assert "TrimLeft" in result.worker_patches["worker-a"]

    # The review loop's evidence: three round-one findings, none surviving round two.
    assert len(result.findings) == 3
    assert result.consolidated is not None
    assert result.consolidated.iteration == 2
    assert not result.consolidated.has_accepted

    # Fan-in recorded every invocation in graph order, rounds in sequence.
    assert [inv.run_id for inv in state.workers.invocations] == EXPECTED_INVOCATION_RUN_IDS
    assert state.budgets.worker_count == 8
    # The budgets aggregate exactly the persisted canonical 9.2 invocation records.
    invocation_ids = [
        ("worker-a", "implement", 1),
        ("worker-b", "implement", 1),
        ("worker-c", "implement", 1),
        ("reviewer-1", "review", 1),
        ("reviewer-2", "review", 1),
        ("reviewer-3", "review", 1),
        ("fixer-1", "fix", 1),
        ("reviewer-1", "review", 2),
    ]
    total = sum(
        float(store.load_artifact("wf-t", f"invocation-{worker}-{stage}-{attempt}")["cost"])
        for worker, stage, attempt in invocation_ids
    )
    assert state.budgets.monetary_used == pytest.approx(total)

    # Eleven stage-boundary checkpoints, exactly one per stage the run passed.
    assert store.versions("wf-t") == tuple(range(1, 12))

    # The artifact trail of the arc: graph, contracts, integration, findings,
    # consolidation, fix assignment, termination report, result.
    for artifact_id in (
        "task-spec-fx-tag-style",
        "task-graph-fx-tag-style",
        "contract-implementer",
        "contract-correctness_reviewer",
        "contract-fix_worker",
        "integration-fx-tag-style-1",
        "validation-fx-tag-style-integrated-1",
        "validation-fx-tag-style-integrated-2",
        "findings-fx-tag-style-reviewer-1-1",
        "consolidated-review-fx-tag-style-1",
        "consolidated-review-fx-tag-style-2",
        "fix-assignment-fx-tag-style-fixer-1",
        "termination-report-fx-tag-style",
        "result-fx-tag-style",
    ):
        assert store.has_artifact("wf-t", artifact_id), artifact_id
    assert len(state.artifacts.review_findings) == 4
    assert state.artifacts.consolidated_review == "consolidated-review-fx-tag-style-2"
    assert result.result_artifact_id == "result-fx-tag-style"
    # Rejected-without-evidence and duplicate findings stay auditable.
    consolidated_one = store.load_artifact("wf-t", "consolidated-review-fx-tag-style-1")
    assert len(consolidated_one["accepted"]) == 1
    assert len(consolidated_one["rejected"]) == 1
    assert len(consolidated_one["duplicates"]) == 1

    # Nothing leaked: the target is clean and every worktree was destroyed.
    assert _clean(repo)


def test_fan_in_is_graph_ordered_regardless_of_concurrency(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    result = _orchestrator(repo, store, _ScriptFactory(), max_concurrency=3).run()
    assert result.state.status.state is WorkflowStatus.COMPLETED
    assert [inv.run_id for inv in result.state.workers.invocations] == (EXPECTED_INVOCATION_RUN_IDS)
    assert result.integrated_patch is not None and "TrimSpace" in result.integrated_patch


class _CountingAdapter(ModelAdapter):
    """Delegates to a scripted adapter while tracking concurrent complete() calls."""

    def __init__(self, inner: ModelAdapter, tracker: dict[str, int], lock: threading.Lock):
        super().__init__(COST_TABLE)
        self._inner = inner
        self._tracker = tracker
        self._lock = lock

    def complete(self, request: ModelRequest) -> ModelResponse:
        with self._lock:
            self._tracker["active"] += 1
            self._tracker["peak"] = max(self._tracker["peak"], self._tracker["active"])
        try:
            time.sleep(0.02)
            return self._inner.complete(request)
        finally:
            with self._lock:
                self._tracker["active"] -= 1

    def capabilities(self) -> ModelCapabilities:
        return self._inner.capabilities()


@pytest.mark.parametrize("bound", [1, 2])
def test_concurrency_limit_is_enforced(tmp_path: Path, bound: int) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    tracker = {"active": 0, "peak": 0}
    lock = threading.Lock()
    inner = _ScriptFactory()

    def factory(worker_id: str, stage: str, attempt: int) -> ModelAdapter:
        return _CountingAdapter(inner(worker_id, stage, attempt), tracker, lock)

    orchestrator = MultiWorkerOrchestrator(
        _load_spec(),
        repo,
        factory,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id="wf-t",
        max_concurrency=bound,
        clock=lambda: CLOCK,
    )
    result = orchestrator.run()
    assert result.state.status.state is WorkflowStatus.COMPLETED
    assert 1 <= tracker["peak"] <= bound


def test_cancellation_is_an_explicit_checkpointed_terminal(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    orchestrator = _orchestrator(repo, store, _ScriptFactory())
    orchestrator.cancel("operator requested stop")
    state = orchestrator.state
    assert state.status.state is WorkflowStatus.CANCELLED
    assert state.status.termination_reason == "cancelled: operator requested stop"
    assert state.status.current_stage == "cancelled"
    assert store.versions("wf-t") == (1,)
    with pytest.raises(MultiWorkflowError, match="terminal"):
        orchestrator.run()
    with pytest.raises(MultiWorkflowError, match="terminal"):
        orchestrator.cancel("again")


def test_loop_terminates_at_the_iteration_limit_with_residual_findings(
    tmp_path: Path,
) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    factory = _ScriptFactory()
    result = _orchestrator(
        repo, store, factory, termination=TerminationPolicy(max_review_iterations=1)
    ).run()
    state = result.state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.termination_reason is not None
    assert "maximum review iterations" in state.status.termination_reason
    assert "unresolved" in state.status.termination_reason
    # The loop stopped BEFORE any fix worker ran: implementers + reviewers only.
    assert state.budgets.worker_count == 6
    assert ("fixer-1", "fix", 1) not in factory.requested
    assert result.consolidated is not None and result.consolidated.has_accepted
    assert _clean(repo)


def test_no_progress_is_detected_and_stops_the_loop(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    repeated_finding = json.dumps(
        {
            "category": "correctness",
            "severity": "high",
            "confidence": "high",
            "summary": "Normalize trims only leading spaces.",
            "evidence": {
                "files": ["internal/tags/normalize.go"],
                "lines": ["7"],
                "tests": [],
                "reasoning": "TrimLeft strips leading spaces only.",
            },
            "impact": "Padded tags stay distinct.",
            "recommended_action": "Use strings.TrimSpace(tag) before lowercasing.",
            "deduplication_key": "tags-normalize-trailing-whitespace",
        }
    )
    overrides = {
        # A fixer that changes NOTHING: completed, validated, approved empty delta.
        ("fixer-1", "fix", 1): [
            _step("I could not identify a safe change; leaving the code as it is.")
        ],
        # The targeted re-review reports the SAME finding again.
        ("reviewer-1", "review", 2): [
            _step(f"FINDING: {repeated_finding}\nCONCLUSION: changes_required")
        ],
    }
    factory = _ScriptFactory(overrides)
    result = _orchestrator(
        repo, store, factory, termination=TerminationPolicy(max_review_iterations=5)
    ).run()
    state = result.state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.termination_reason is not None
    assert "no progress" in state.status.termination_reason
    # Two review rounds happened; the loop refused a third.
    assert result.review_iterations == 2
    assert ("reviewer-1", "review", 3) not in factory.requested
    assert _clean(repo)


def _two_worker_overlap_spec() -> MultiWorkerSpec:
    base = _load_spec()
    node_a = base.graph.nodes[0]
    node_x = TaskNode(
        worker_id="worker-x",
        description="Uppercase tags in tags.Normalize instead of lowercasing.",
        acceptance_criteria=("Normalize uppercases.",),
        owned_paths=("internal/tags/normalize.go",),
        search_terms=("Normalize",),
    )
    return MultiWorkerSpec(
        task_id=base.task_id,
        description=base.description,
        acceptance_criteria=base.acceptance_criteria,
        graph=TaskGraph(task_id=base.task_id, nodes=(node_a, node_x)),
        reviewers=base.reviewers[:1],
        token_budget=base.token_budget,
    )


def _worker_x_steps() -> list[ScriptStep]:
    return [
        _step("The change point is internal/tags/normalize.go."),
        _step(
            "Uppercasing the tag.",
            tool_calls=[
                {
                    "id": "call-worker-x-1",
                    "name": "replace_text",
                    "arguments": {
                        "path": "internal/tags/normalize.go",
                        "old_text": "\treturn strings.ToLower(tag)\n",
                        "new_text": "\treturn strings.ToUpper(tag)\n",
                    },
                }
            ],
        ),
        _step("The edit for worker-x is in place."),
    ]


def test_prohibited_overlap_escalates_before_any_apply(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    factory = _ScriptFactory({("worker-x", "implement", 1): _worker_x_steps()})
    orchestrator = MultiWorkerOrchestrator(
        _two_worker_overlap_spec(),
        repo,
        factory,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id="wf-t",
        overlap_policy=OverlapPolicy(prohibited_paths=("internal/tags/normalize.go",)),
        clock=lambda: CLOCK,
    )
    result = orchestrator.run()
    state = result.state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.termination_reason is not None
    assert "prohibited overlap" in state.status.termination_reason
    assert "internal/tags/normalize.go" in state.status.termination_reason
    assert result.integrated_patch is None
    assert _clean(repo)


def test_integration_conflict_escalates_with_recorded_evidence(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: CLOCK)
    factory = _ScriptFactory({("worker-x", "implement", 1): _worker_x_steps()})
    orchestrator = MultiWorkerOrchestrator(
        _two_worker_overlap_spec(),
        repo,
        factory,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id="wf-t",
        clock=lambda: CLOCK,
    )
    result = orchestrator.run()
    state = result.state
    assert state.status.state is WorkflowStatus.ESCALATED
    assert state.status.termination_reason is not None
    assert "integration conflict" in state.status.termination_reason
    assert "worker-x" in state.status.termination_reason
    # The conflict evidence is a persisted artifact, not a log line.
    report = store.load_artifact("wf-t", "integration-fx-tag-style-1")
    assert report["ok"] is False
    assert report["applied"] == ["worker-a"]
    rejected = report["rejected"]
    assert len(rejected) == 1 and rejected[0]["worker_id"] == "worker-x"
    assert "normalize.go" in rejected[0]["error"]
    assert rejected[0]["conflicted_paths"] == ["internal/tags/normalize.go"]
    # The file-level overlap was identified and classified before the apply.
    assert report["overlaps"][0]["classification"] == "review_required"
    assert _clean(repo)
