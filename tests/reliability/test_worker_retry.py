"""Worker retry bumps the attempt segment (Lesson 7.3).

A retried Module 6 worker MUST run under a bumped ``attempt`` - the attempt segment
namespaces its run ids, event ids, trace file, and sandbox branch, so the retry can
never collide with the failed attempt's residue. These fail against the scaffolding
stubs and pass once Modules 6 and 7 are implemented to the reference behaviour.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.models import CostTable, ScriptedAdapter
from anse_harness.models.errors import ProviderError
from anse_harness.reliability import (
    FailureInjectionAdapter,
    InjectionSpec,
    run_worker_attempts,
)
from anse_harness.tracing import TraceWriter, read_trace
from anse_harness.validation.pipeline import ValidationCheck
from anse_harness.workers.contract import implementer_contract
from anse_harness.workers.runner import ImplementationWorkerResult, run_implementation_worker
from anse_harness.workflows.graph import TaskNode

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m06"
COST = CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)
CLOCK = "2026-01-01T00:00:00+00:00"


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


def _node() -> tuple[TaskNode, str]:
    raw = json.loads((FIXTURES / "multiworker_task.json").read_text(encoding="utf-8"))
    node = raw["graph"]["nodes"][0]
    return (
        TaskNode(
            worker_id=node["worker_id"],
            description=node["description"],
            acceptance_criteria=tuple(node["acceptance_criteria"]),
            owned_paths=tuple(node["owned_paths"]),
            depends_on=tuple(node["depends_on"]),
            search_terms=tuple(node["search_terms"]),
        ),
        raw["task_id"],
    )


def _scripted() -> ScriptedAdapter:
    return ScriptedAdapter.from_file(FIXTURES / "scripts" / "worker_a.script.json", cost_table=COST)


def test_worker_retry_runs_under_a_bumped_attempt_segment(target: Path, tmp_path: Path) -> None:
    node, task_id = _node()
    traces = {1: tmp_path / "worker_a_attempt1.jsonl", 2: tmp_path / "worker_a_attempt2.jsonl"}
    invoked: list[int] = []

    def invoke(attempt: int) -> ImplementationWorkerResult:
        invoked.append(attempt)
        injection = InjectionSpec(at_call=2, failure="model_timeout") if attempt == 1 else None
        with TraceWriter(traces[attempt]) as writer:
            return run_implementation_worker(
                node,
                task_id,
                target,
                FailureInjectionAdapter(_scripted(), injection),
                gate=ApprovalGate(approve_all),
                checks=(ValidationCheck("format-check", ("git", "diff", "--check")),),
                contract=implementer_contract(),
                workflow_id="wf-worker-retry-test",
                attempt=attempt,
                tracer=writer,
                clock=lambda: CLOCK,
            )

    result, attempts_used, decisions = run_worker_attempts(invoke)

    assert invoked == [1, 2]
    assert attempts_used == 2
    assert result.status == "completed"
    assert result.patch is not None and "TrimLeft" in result.patch
    assert [decision.action for decision in decisions] == ["retry"]
    assert decisions[0].failure_class == "model-provider failure"
    # The failed attempt's worktree was cleaned up: no residue for the retry.
    assert (
        not any((target.parent / ".anse-worktrees").glob("*"))
        or not (target.parent / ".anse-worktrees").exists()
    )
    # The attempt segment namespaces EVERYTHING: zero event-id overlap between the
    # two attempts' trace files, and the run ids carry the attempt number.
    first_ids = [event.event_id for event in read_trace(traces[1])]
    second_ids = [event.event_id for event in read_trace(traces[2])]
    assert first_ids and second_ids
    assert not set(first_ids) & set(second_ids)
    assert all(run_id.endswith("-1") for run_id in {e.run_id for e in read_trace(traces[1])})
    assert all(run_id.endswith("-2") for run_id in {e.run_id for e in read_trace(traces[2])})


def test_worker_permanent_failure_is_reraised_without_a_second_attempt(
    target: Path, tmp_path: Path
) -> None:
    node, task_id = _node()
    invoked: list[int] = []

    def invoke(attempt: int) -> ImplementationWorkerResult:
        invoked.append(attempt)
        return run_implementation_worker(
            node,
            task_id,
            target,
            FailureInjectionAdapter(
                _scripted(),
                InjectionSpec(at_call=1, failure="provider_error_permanent"),
            ),
            gate=ApprovalGate(approve_all),
            checks=(ValidationCheck("format-check", ("git", "diff", "--check")),),
            contract=implementer_contract(),
            workflow_id="wf-worker-retry-test",
            attempt=attempt,
            clock=lambda: CLOCK,
        )

    with pytest.raises(ProviderError) as info:
        run_worker_attempts(invoke)
    assert info.value.retryable is False
    # ONE invocation only: the permanent error was not blindly retried.
    assert invoked == [1]
