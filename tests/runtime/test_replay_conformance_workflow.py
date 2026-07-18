"""Replay conformance for the stateful workflow run (Module 5).

The recorded workflow run - context-driven investigation, one planning call, plan
approval, a sandboxed write run, validation, and result preparation - is driven by the
real ``ReplayAdapter`` over ``traces/m05/workflow_feature_task.jsonl``. A clean replay
proves the whole staged path is deterministic end to end: the packet construction and
rendering inside Investigate, the pinned planning request, the plan-derived
implementation task, and every write-run request reproduce the recorded requests byte
for byte, across all three model-driven stages sharing one trace file.

The Module 5 fixture tree is materialized into a real one-commit git repository with
the same pinned identity and date as Modules 3 and 4, and the engine clock is pinned,
so the revision and timestamps inside the packet (and therefore inside the rendered
prompts) are identical on every machine. Both must stay in lockstep with the reference
trace-generation entry point.

These fail against the scaffolding stubs and pass once the state store and the
workflow engine are implemented to the reference behaviour.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.models import ReplayAdapter
from anse_harness.state.store import WorkflowStateStore
from anse_harness.workflows.engine import WorkflowEngine, WorkflowTaskSpec
from anse_harness.workflows.plan import render_plan_request
from anse_harness.workflows.state import WorkflowStatus

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m05"
TRACE = Path(__file__).resolve().parents[2] / "traces" / "m05" / "workflow_feature_task.jsonl"

#: Pinned identity and date, so the materialized fixture repository has the same base
#: revision on every machine. Must match the reference trace-generation entry point.
PINNED_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "ANSE Course",
    "GIT_AUTHOR_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_NAME": "ANSE Course",
    "GIT_COMMITTER_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

#: Pinned engine clock for the recorded run. Must match the reference entry point.
PINNED_CLOCK_ISO = "2026-01-01T00:00:00+00:00"


def _materialize_fixture_repo(tmp_path: Path) -> Path:
    """Copy the fixture tree and turn it into a pinned one-commit git repository."""
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


def _spec() -> WorkflowTaskSpec:
    raw = json.loads((FIXTURES / "workflow_task.json").read_text(encoding="utf-8"))
    terms = raw.get("search_terms")
    return WorkflowTaskSpec(
        task_id=raw["task_id"],
        description=raw["description"],
        acceptance_criteria=tuple(raw["acceptance_criteria"]),
        worker_type=raw["worker_type"],
        token_budget=raw["token_budget"],
        search_terms=tuple(terms) if terms is not None else None,
        conflict_topics=tuple(raw["conflict_topics"]),
    )


def test_workflow_replays_recorded_trace_without_mismatch(tmp_path: Path) -> None:
    repo = _materialize_fixture_repo(tmp_path)
    spec = _spec()
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: PINNED_CLOCK_ISO)

    engine = WorkflowEngine(
        spec,
        repo,
        ReplayAdapter(TRACE),
        store,
        gate=ApprovalGate(approve_all),
        max_cost_usd=1.0,
        clock=lambda: PINNED_CLOCK_ISO,
    )
    result = engine.run()

    state = result.state
    assert state.status.state is WorkflowStatus.COMPLETED
    assert state.status.termination_reason == "completed"
    assert result.validation_ok is True
    assert result.patch is not None and "strings.ReplaceAll" in result.patch
    assert result.investigation_answer is not None
    assert "internal/directory/slug.go" in result.investigation_answer

    # Seven boundary checkpoints, exactly as recorded.
    assert store.versions(state.workflow_id) == (1, 2, 3, 4, 5, 6, 7)

    # The fixture ships the rendered planning request of the recorded run, so a
    # student build can spot rendering drift directly. If rendering drifted, the
    # replay above would already have mismatched.
    shipped = (FIXTURES / "plan_request.txt").read_text(encoding="utf-8").rstrip("\n")
    assert (
        render_plan_request(
            spec.task_id,
            spec.description,
            spec.acceptance_criteria,
            result.investigation_answer,
        )
        == shipped
    )
