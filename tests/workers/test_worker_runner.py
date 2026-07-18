"""The worker runtime: fresh, bounded, isolated worker execution (Lessons 6.4-6.7).

Exercises the three worker runners over the Module 6 fixture repository: patch
production in isolated worktrees, worker-scoped run ids in per-worker trace files,
worker independence at the tool layer (a worker cannot reach a sibling's worktree),
per-worker budgets, reviewer freshness (no implementer reasoning history), and the
fix worker's bounded context (accepted findings, never the review conversation).
These fail against the scaffolding stubs and pass once the worker runtime is
implemented to the reference behaviour.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.models import CostTable, ScriptedAdapter, ScriptStep
from anse_harness.models.types import response_from_payload
from anse_harness.review.findings import FindingEvidence, FindingStatus, ReviewFinding
from anse_harness.runtime.sandbox import SandboxManager
from anse_harness.tracing import TraceWriter, read_trace
from anse_harness.validation.pipeline import ValidationCheck
from anse_harness.workers.contract import (
    WRITE_CAPABILITIES,
    fix_worker_contract,
    implementer_contract,
    reviewer_contract,
)
from anse_harness.workers.runner import (
    WorkerError,
    head_revision,
    run_fix_worker,
    run_implementation_worker,
    run_review_worker,
)
from anse_harness.workflows.graph import TaskNode

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m06"
COST_TABLE = CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)
CHECKS = (ValidationCheck("format-check", ("git", "diff", "--check")),)
CLOCK = "2026-01-01T00:00:00+00:00"

PINNED_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "ANSE Course",
    "GIT_AUTHOR_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_NAME": "ANSE Course",
    "GIT_COMMITTER_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


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


def _script(name: str) -> ScriptedAdapter:
    return ScriptedAdapter.from_file(
        FIXTURES / "scripts" / f"{name}.script.json", cost_table=COST_TABLE
    )


def _worker_a_node() -> TaskNode:
    raw = json.loads((FIXTURES / "multiworker_task.json").read_text(encoding="utf-8"))
    node = raw["graph"]["nodes"][0]
    return TaskNode(
        worker_id=node["worker_id"],
        description=node["description"],
        acceptance_criteria=tuple(node["acceptance_criteria"]),
        owned_paths=tuple(node["owned_paths"]),
        depends_on=tuple(node["depends_on"]),
        search_terms=tuple(node["search_terms"]),
    )


def _clean(repo: Path) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    )
    worktrees = repo.parent / ".anse-worktrees"
    return status.stdout.strip() == "" and (not worktrees.exists() or not any(worktrees.iterdir()))


ACCEPTED_FINDING = ReviewFinding(
    finding_id="finding-reviewer-1-1-1",
    reviewer_type="correctness_reviewer",
    category="correctness",
    severity="high",
    confidence="high",
    summary="Normalize trims only leading spaces, so trailing whitespace survives normalization.",
    evidence=FindingEvidence(
        files=("internal/tags/normalize.go",),
        lines=("7",),
        reasoning="TrimLeft strips leading spaces only.",
    ),
    impact="Padded tags stay distinct.",
    recommended_action="Use strings.TrimSpace(tag) before lowercasing.",
    deduplication_key="tags-normalize-trailing-whitespace",
    status=FindingStatus.ACCEPTED,
)


def test_implementation_worker_produces_patch_in_an_isolated_worktree(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    result = run_implementation_worker(
        _worker_a_node(),
        "fx-tag-style",
        repo,
        _script("worker_a"),
        gate=ApprovalGate(approve_all),
        checks=CHECKS,
        contract=implementer_contract(),
        workflow_id="wf-t",
        clock=lambda: CLOCK,
    )
    assert result.status == "completed"
    assert result.patch is not None and "TrimLeft" in result.patch
    assert result.base_revision == head_revision(repo)
    assert result.investigation_answer is not None
    assert result.validation_report is not None and result.validation_report.ok
    assert result.cost_usd > 0
    # The target itself was never written to, and the worktree is gone.
    assert _clean(repo)
    # The canonical 9.2 lineage record is populated.
    invocation = result.invocation
    assert invocation.worker_invocation_id == "wf-t-worker-a-implement-1"
    assert invocation.assigned_task == "fx-tag-style/worker-a"
    assert invocation.available_capabilities == WRITE_CAPABILITIES
    assert invocation.parent_workflow == "wf-t"
    assert invocation.status == "completed"


def test_worker_runs_are_traced_under_worker_scoped_run_ids(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    trace_path = tmp_path / "worker_a.jsonl"
    with TraceWriter(trace_path) as tracer:
        run_implementation_worker(
            _worker_a_node(),
            "fx-tag-style",
            repo,
            _script("worker_a"),
            gate=ApprovalGate(approve_all),
            checks=CHECKS,
            contract=implementer_contract(),
            workflow_id="wf-t",
            tracer=tracer,
            clock=lambda: CLOCK,
        )
    events = read_trace(trace_path)
    run_ids = {event.run_id for event in events}
    assert run_ids == {
        "run-wf-t-worker-a-investigate-1",
        "run-wf-t-worker-a-implement-1",
    }
    event_ids = [event.event_id for event in events]
    assert len(event_ids) == len(set(event_ids))
    # Both inner loops restart at evt-0000; the run-id prefix keeps them unique.
    assert any(event_id.startswith("run-wf-t-worker-a-investigate-1:") for event_id in event_ids)
    assert any(event_id.startswith("run-wf-t-worker-a-implement-1:") for event_id in event_ids)


def test_workers_cannot_reach_a_sibling_worktree(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    manager = SandboxManager(repo)
    sibling = manager.create("wf-t-worker-b-implement-1")
    try:
        escape = f"../{sibling.worktree.name}/internal/tags/normalize.go"
        adapter = ScriptedAdapter(
            [
                ScriptStep(
                    response=response_from_payload(
                        {
                            "text": "Investigation done.",
                            "tool_calls": [],
                            "structured_output": None,
                            "usage": {"input_tokens": 100, "output_tokens": 10},
                            "stop_reason": "end_turn",
                        }
                    )
                ),
                ScriptStep(
                    response=response_from_payload(
                        {
                            "text": "Reading the sibling worktree.",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "name": "read_file",
                                    "arguments": {"path": escape},
                                }
                            ],
                            "structured_output": None,
                            "usage": {"input_tokens": 100, "output_tokens": 10},
                            "stop_reason": "tool_use",
                        }
                    )
                ),
            ],
            COST_TABLE,
        )
        result = run_implementation_worker(
            _worker_a_node(),
            "fx-tag-style",
            repo,
            adapter,
            gate=ApprovalGate(approve_all),
            checks=CHECKS,
            contract=implementer_contract(),
            workflow_id="wf-t",
        )
        # The escape was refused at the tool layer: the run fails safely, no patch.
        assert result.status == "failed"
        assert result.patch is None
        # The sibling worktree is untouched.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=sibling.worktree,
            capture_output=True,
            text=True,
            check=True,
        )
        assert status.stdout.strip() == ""
    finally:
        manager.destroy(sibling)
    assert _clean(repo)


def test_per_worker_cost_budget_escalates(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    result = run_implementation_worker(
        _worker_a_node(),
        "fx-tag-style",
        repo,
        _script("worker_a"),
        gate=ApprovalGate(approve_all),
        checks=CHECKS,
        contract=implementer_contract(cost_budget_usd=0.000000001),
        workflow_id="wf-t",
        clock=lambda: CLOCK,
    )
    assert result.status == "escalated"
    assert result.patch is None
    assert result.invocation.status == "escalated"
    assert _clean(repo)


def test_review_worker_is_fresh_and_parses_structured_findings(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    implementer = run_implementation_worker(
        _worker_a_node(),
        "fx-tag-style",
        repo,
        _script("worker_a"),
        gate=ApprovalGate(approve_all),
        checks=CHECKS,
        contract=implementer_contract(),
        workflow_id="wf-t",
        clock=lambda: CLOCK,
    )
    assert implementer.patch is not None and implementer.investigation_answer is not None
    # Review the change over a worktree carrying it (integration is exercised
    # elsewhere; here a plain sandbox stands in for the integrated result).
    manager = SandboxManager(repo)
    sandbox = manager.create("wf-t-integration-1")
    trace_path = tmp_path / "reviewer_1.jsonl"
    try:
        subprocess.run(
            ["git", "apply", "--index"],
            cwd=sandbox.worktree,
            input=implementer.patch,
            capture_output=True,
            text=True,
            check=True,
        )
        with TraceWriter(trace_path) as tracer:
            result = run_review_worker(
                "reviewer-1",
                "correctness",
                "fx-tag-style",
                "Venue tags must render consistently.",
                ('Normalize(" Jazz ") returns "jazz".',),
                sandbox.worktree,
                implementer.patch,
                "format-check: ok",
                _script("reviewer_1"),
                revision=sandbox.base_revision,
                contract=reviewer_contract("correctness"),
                workflow_id="wf-t",
                iteration=1,
                search_terms=("normalize",),
                tracer=tracer,
                clock=lambda: CLOCK,
            )
    finally:
        manager.destroy(sandbox)
    assert result.status == "completed"
    assert result.conclusion == "changes_required"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.finding_id == "finding-reviewer-1-1-1"
    assert finding.deduplication_key == "tags-normalize-trailing-whitespace"
    assert finding.status is FindingStatus.PROPOSED
    assert not finding.evidence.is_empty()
    # Reviewer freshness (arch-ref 43): the reviewer's requests carry the diff and
    # validation results - and none of the implementer's reasoning history.
    events = read_trace(trace_path)
    requests = [
        json.dumps(event.payload) for event in events if event.event_type == "model_requested"
    ]
    assert requests, "reviewer requests must be traced"
    assert all("performs no whitespace handling today" not in request for request in requests)
    assert any("TrimLeft" in request for request in requests)
    assert any("format-check: ok" in request for request in requests)
    assert all(event.run_id == "run-wf-t-reviewer-1-review-1" for event in events)


def test_review_rounds_are_fresh_invocations_with_bumped_run_ids(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    trace_path = tmp_path / "reviewer_1_round_2.jsonl"
    with TraceWriter(trace_path) as tracer:
        result = run_review_worker(
            "reviewer-1",
            "correctness",
            "fx-tag-style",
            "Venue tags must render consistently.",
            ("criteria",),
            repo,
            "",
            "format-check: ok",
            _script("reviewer_1_round_2"),
            revision=head_revision(repo),
            contract=reviewer_contract("correctness"),
            workflow_id="wf-t",
            iteration=2,
            tracer=tracer,
            clock=lambda: CLOCK,
        )
    assert result.status == "completed"
    assert result.findings == ()
    assert result.conclusion == "approved"
    events = read_trace(trace_path)
    # A re-review is a NEW invocation: the bumped iteration segment keeps its
    # event ids distinct from round one's (deterministic ids per run id).
    assert all(event.run_id == "run-wf-t-reviewer-1-review-2" for event in events)
    assert result.invocation.worker_invocation_id == "wf-t-reviewer-1-review-2"


def test_fix_worker_gets_bounded_context_and_produces_the_fix_delta(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    implementer = run_implementation_worker(
        _worker_a_node(),
        "fx-tag-style",
        repo,
        _script("worker_a"),
        gate=ApprovalGate(approve_all),
        checks=CHECKS,
        contract=implementer_contract(),
        workflow_id="wf-t",
        clock=lambda: CLOCK,
    )
    assert implementer.patch is not None
    trace_path = tmp_path / "fixer_1.jsonl"
    with TraceWriter(trace_path) as tracer:
        result = run_fix_worker(
            "fixer-1",
            (ACCEPTED_FINDING,),
            "fx-tag-style",
            ('Normalize(" Jazz ") returns "jazz".',),
            repo,
            implementer.patch,
            _script("fixer_1"),
            gate=ApprovalGate(approve_all),
            checks=CHECKS,
            contract=fix_worker_contract(),
            workflow_id="wf-t",
            tracer=tracer,
        )
    assert result.status == "completed"
    # The fix patch is the DELTA against the integrated state it was seeded with.
    assert result.fix_patch is not None
    assert "TrimSpace" in result.fix_patch
    assert "TrimLeft" in result.fix_patch  # the replaced line appears as removal
    assert "render.go" not in result.fix_patch
    assert _clean(repo)
    # Bounded fixer context (arch-ref 46): the request carries the finding and its
    # evidence - never the review conversation.
    events = read_trace(trace_path)
    requests = [
        json.dumps(event.payload) for event in events if event.event_type == "model_requested"
    ]
    assert any("Resolve the following accepted review findings" in request for request in requests)
    assert any(ACCEPTED_FINDING.summary in request for request in requests)
    assert all("CONCLUSION" not in request for request in requests)


def test_fix_worker_refuses_an_unappliable_integrated_diff(tmp_path: Path) -> None:
    repo = _materialize_repo(tmp_path)
    with pytest.raises(WorkerError, match="does not apply"):
        run_fix_worker(
            "fixer-1",
            (ACCEPTED_FINDING,),
            "fx-tag-style",
            ("criteria",),
            repo,
            "not a diff at all\n",
            _script("fixer_1"),
            gate=ApprovalGate(approve_all),
            checks=CHECKS,
            contract=fix_worker_contract(),
            workflow_id="wf-t",
        )
    assert _clean(repo)
