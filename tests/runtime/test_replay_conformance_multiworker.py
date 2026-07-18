"""Replay conformance for the multi-worker trace SET (Module 6).

The recorded multi-worker run - three implementation workers, integration,
deterministic validation, three fresh reviewers, consolidation, one fix worker, and a
targeted re-review - is driven by real ``ReplayAdapter`` instances, ONE PER WORKER
TRACE FILE, over ``traces/m06/``. That layout is the Module 6 determinism boundary:
each worker's byte-exact discipline lives in its own file with its own adapter, so
worker order and scheduling do not exist in the trace layout, and the committed set
replays sequentially in graph order (exactly how it was recorded).

A clean replay proves the whole fan-out path is deterministic end to end: every
worker packet, every rendered task (including the review request that embeds the
integrated diff, and the fix task rendered from the accepted finding) reproduces the
recorded requests byte for byte, and the replayed integrated patch is byte-identical
to the recorded one. The orchestrator's own file carries no model interactions - its
determinism is checked structurally against the replayed run's transition sequence.

The fixture repository, identity, and clock are pinned exactly as in Modules 3-5 and
must stay in lockstep with the reference trace-generation entry point.

These fail against the scaffolding stubs and pass once the Module 6 harness is
implemented to the reference behaviour.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.budgets.policy import TerminationPolicy
from anse_harness.models import CostTable, ModelAdapter, ReplayAdapter
from anse_harness.state.store import WorkflowStateStore
from anse_harness.tracing import read_trace
from anse_harness.workflows.graph import TaskGraph
from anse_harness.workflows.orchestrator import (
    MultiWorkerOrchestrator,
    MultiWorkerSpec,
    ReviewerSpec,
    worker_trace_filename,
)
from anse_harness.workflows.state import WorkflowStatus

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m06"
TRACES = Path(__file__).resolve().parents[2] / "traces" / "m06"
COST_TABLE = CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)

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

#: Pinned clock for the recorded run. Must match the reference entry point.
PINNED_CLOCK_ISO = "2026-01-01T00:00:00+00:00"

#: The complete recorded set: one file per worker invocation plus the orchestrator.
WORKER_TRACE_FILES = {
    "worker_a.jsonl",
    "worker_b.jsonl",
    "worker_c.jsonl",
    "reviewer_1.jsonl",
    "reviewer_2.jsonl",
    "reviewer_3.jsonl",
    "fixer_1.jsonl",
    "reviewer_1_round_2.jsonl",
}


def _materialize_fixture_repo(tmp_path: Path) -> Path:
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


def _spec() -> MultiWorkerSpec:
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


def test_multiworker_replays_every_recorded_trace_file_without_mismatch(
    tmp_path: Path,
) -> None:
    repo = _materialize_fixture_repo(tmp_path)
    store = WorkflowStateStore(tmp_path / "state", clock=lambda: PINNED_CLOCK_ISO)
    replayed_files: list[str] = []

    def adapters(worker_id: str, stage: str, attempt: int) -> ModelAdapter:
        name = worker_trace_filename(worker_id, attempt)
        replayed_files.append(name)
        return ReplayAdapter(TRACES / name, COST_TABLE)

    orchestrator = MultiWorkerOrchestrator(
        _spec(),
        repo,
        adapters,
        store,
        gate=ApprovalGate(approve_all),
        workflow_id="wf-m06-multiworker",
        max_concurrency=1,
        termination=TerminationPolicy(max_review_iterations=2),
        clock=lambda: PINNED_CLOCK_ISO,
    )
    result = orchestrator.run()

    state = result.state
    assert state.status.state is WorkflowStatus.COMPLETED
    assert state.status.termination_reason == "completed"
    assert result.review_iterations == 2
    assert result.validation_ok is True

    # EVERY file of the committed set drove exactly one worker's replay.
    assert set(replayed_files) == WORKER_TRACE_FILES
    assert len(replayed_files) == len(WORKER_TRACE_FILES)

    # The replayed integrated patch is byte-identical to the recorded one (the
    # result artifact in the orchestrator trace carries the recorded bytes).
    orchestrator_events = read_trace(TRACES / "orchestrator.jsonl")
    recorded_result = next(
        event.payload
        for event in orchestrator_events
        if event.event_type == "artifact_created" and event.payload.get("artifact_type") == "result"
    )
    assert result.integrated_patch is not None
    assert result.integrated_patch == recorded_result["integrated_patch"]
    assert "TrimSpace" in result.integrated_patch

    # The orchestrator's own file holds no model interactions - all model traffic
    # lives in the per-worker files - and its recorded stage transitions match the
    # replayed run's path through the stage graph exactly.
    assert not [
        event
        for event in orchestrator_events
        if event.event_type in ("model_requested", "model_responded")
    ]
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
        ("consolidate", "prepare_result"),
        ("prepare_result", "completed"),
    ]

    # One boundary checkpoint per recorded stage, reproduced by the replay.
    assert store.versions("wf-m06-multiworker") == tuple(range(1, 12))
