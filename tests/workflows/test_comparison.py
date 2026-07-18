"""The single-worker vs multi-worker comparison harness (Evidence Gate 4 substrate).

Runs the SAME Module 6 fixture task through the Module 5 single-worker workflow and
the Module 6 orchestrator, then reduces both to the comparison report - the required
validation that "a single-worker comparison is available" (spec section 16, Module 6).
The report states measurements, not a verdict: a negative result is a valid Evidence
Gate 4 outcome. These fail against the scaffolding stubs and pass once the harness is
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
from anse_harness.state.store import WorkflowStateStore
from anse_harness.workflows.comparison import build_comparison_report, comparison_artifact_id
from anse_harness.workflows.engine import WorkflowEngine, WorkflowResult, WorkflowTaskSpec
from anse_harness.workflows.graph import TaskGraph
from anse_harness.workflows.orchestrator import (
    MultiWorkerOrchestrator,
    MultiWorkerResult,
    MultiWorkerSpec,
    ReviewerSpec,
    worker_trace_filename,
)

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


def _materialize_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    shutil.copytree(FIXTURES / "repo", repo)
    env = {**os.environ, **PINNED_COMMIT_ENV}
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "-c", "core.autocrlf=false", "add", "-A"],
        ["git", "commit", "-q", "-m", "Practice fixture baseline"],
    ):
        subprocess.run(args, cwd=repo, env=env, check=True, capture_output=True)
    return repo


def _step(text: str, tool_calls: list[dict[str, object]] | None = None) -> ScriptStep:
    return ScriptStep(
        response=response_from_payload(
            {
                "text": text,
                "tool_calls": tool_calls or [],
                "structured_output": None,
                "usage": {"input_tokens": 1500, "output_tokens": 60},
                "stop_reason": "tool_use" if tool_calls else "end_turn",
            }
        )
    )


def _edit(call_id: str, path: str, old: str, new: str) -> dict[str, object]:
    return {
        "id": call_id,
        "name": "replace_text",
        "arguments": {"path": path, "old_text": old, "new_text": new},
    }


def _run_single_worker(tmp_path: Path) -> WorkflowResult:
    raw = json.loads((FIXTURES / "multiworker_task.json").read_text(encoding="utf-8"))
    repo = _materialize_repo(tmp_path, "repo-single")
    spec = WorkflowTaskSpec(
        task_id=raw["task_id"],
        description=raw["description"],
        acceptance_criteria=tuple(raw["acceptance_criteria"]),
        search_terms=("Normalize", "Render", "Badge"),
    )
    adapter = ScriptedAdapter(
        [
            _step(
                "The three change points are internal/tags/normalize.go, "
                "internal/labels/render.go, and internal/badges/badge.go."
            ),
            _step(
                "1. Trim and lowercase in Normalize.\n"
                "2. Switch Render to angle brackets.\n"
                "3. Switch the Badge prefix to tag:."
            ),
            _step(
                "Applying all three edits.",
                tool_calls=[
                    _edit(
                        "call-s-1",
                        "internal/tags/normalize.go",
                        "\treturn strings.ToLower(tag)\n",
                        "\treturn strings.ToLower(strings.TrimSpace(tag))\n",
                    ),
                    _edit(
                        "call-s-2",
                        "internal/labels/render.go",
                        '\treturn "[" + label + "]"\n',
                        '\treturn "<" + label + ">"\n',
                    ),
                    _edit(
                        "call-s-3",
                        "internal/badges/badge.go",
                        '\treturn "badge " + label\n',
                        '\treturn "tag:" + label\n',
                    ),
                ],
            ),
            _step("All three edits are in place; the change is complete."),
        ],
        COST_TABLE,
    )
    store = WorkflowStateStore(tmp_path / "state-single", clock=lambda: CLOCK)
    engine = WorkflowEngine(
        spec,
        repo,
        adapter,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id="wf-single",
        max_cost_usd=1.0,
        clock=lambda: CLOCK,
    )
    return engine.run()


def _run_multi_worker(tmp_path: Path) -> MultiWorkerResult:
    raw = json.loads((FIXTURES / "multiworker_task.json").read_text(encoding="utf-8"))
    repo = _materialize_repo(tmp_path, "repo-multi")
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

    def adapters(worker_id: str, stage: str, attempt: int) -> ScriptedAdapter:
        stem = worker_trace_filename(worker_id, attempt).removesuffix(".jsonl")
        return ScriptedAdapter.from_file(
            FIXTURES / "scripts" / f"{stem}.script.json", cost_table=COST_TABLE
        )

    store = WorkflowStateStore(tmp_path / "state-multi", clock=lambda: CLOCK)
    orchestrator = MultiWorkerOrchestrator(
        spec,
        repo,
        adapters,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id="wf-multi",
        clock=lambda: CLOCK,
    )
    return orchestrator.run()


def test_comparison_report_measures_both_architectures_on_one_task(tmp_path: Path) -> None:
    single = _run_single_worker(tmp_path)
    multi = _run_multi_worker(tmp_path)
    assert single.state.status.state.value == "completed"
    assert multi.state.status.state.value == "completed"

    report = build_comparison_report("fx-tag-style", single, multi)
    assert report.task_id == "fx-tag-style"
    assert report.single.architecture == "single-worker"
    assert report.multi.architecture == "multi-worker"
    assert report.single.outcome == "completed"
    assert report.multi.outcome == "completed"
    assert report.single.patch_produced and report.multi.patch_produced
    # The single-worker run has no review loop by construction; the multi run does.
    assert report.single.review_iterations == 0
    assert report.single.accepted_findings == 0
    assert report.multi.review_iterations == 2
    assert report.multi.worker_invocations == 8
    assert report.single.worker_invocations == 2
    # The deltas are the measured dimensions, not a verdict.
    assert report.cost_delta_usd == pytest.approx(
        report.multi.monetary_cost_usd - report.single.monetary_cost_usd
    )
    assert report.worker_delta == 6
    assert report.multi.monetary_cost_usd == pytest.approx(multi.state.budgets.monetary_used)


def test_comparison_report_serializes_and_renders_without_a_conclusion(
    tmp_path: Path,
) -> None:
    single = _run_single_worker(tmp_path)
    multi = _run_multi_worker(tmp_path)
    report = build_comparison_report("fx-tag-style", single, multi)
    payload = report.to_payload()
    assert payload["artifact_type"] == "comparison_report"
    assert payload["single"]["architecture"] == "single-worker"
    assert payload["cost_delta_usd"] == report.cost_delta_usd
    rendered = report.render()
    assert "single-worker" in rendered and "multi-worker" in rendered
    assert "cost delta" in rendered
    # The report is deliberately conclusion-free (Evidence Gate 4 is the human's).
    assert "advantage" not in rendered and "justified" not in rendered
    assert comparison_artifact_id("fx-tag-style") == "comparison-fx-tag-style"
