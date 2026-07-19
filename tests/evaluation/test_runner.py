"""Evaluation-runner exercises (Lessons 8.2-8.5): the matrix, the reset discipline,
grading, and the infrastructure-vs-task distinction.

The executors here are synthetic - the runner's contract is independent of which
runtime produced the attempt - and every probe targets a required validation of the
module: fresh clones between runs, complete matrix recording with configuration and
grader versions, cost/duration/tool-calls from the trace, and Module 7 classification
of attempt faults.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from anse_harness.evaluation.graders import CommandGrader, Grader, GraderResult
from anse_harness.evaluation.runner import (
    EVAL_WORKFLOW_ID,
    AttemptOutcome,
    AttemptRequest,
    EvalConfiguration,
    EvalMatrix,
    EvalTask,
    EvaluationRunner,
    attempt_trace_filename,
    eval_run_id,
    patch_sha256,
)
from anse_harness.models.errors import ModelTimeoutError, ReplayExhaustedError
from anse_harness.tracing import TraceEvent, TraceWriter

pytestmark = pytest.mark.student_impl

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@invalid",
}


@pytest.fixture()
def target_source(tmp_path: Path) -> Path:
    """A one-commit target repository plus a real patch against it."""
    source = tmp_path / "target-source"
    source.mkdir()
    (source / "notes.txt").write_text("baseline\n", encoding="utf-8")
    env = {**os.environ, **_GIT_ENV}
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "baseline"],
    ):
        subprocess.run(args, cwd=source, env=env, check=True, capture_output=True)
    return source


def _patch_for(source: Path, tmp_path: Path) -> str:
    """A genuine unified diff that applies cleanly to a fresh clone of ``source``."""
    scratch = tmp_path / "patch-scratch"
    subprocess.run(
        ["git", "clone", "-q", str(source), str(scratch)], check=True, capture_output=True
    )
    (scratch / "notes.txt").write_text("baseline\nchanged\n", encoding="utf-8")
    diff = subprocess.run(["git", "diff"], cwd=scratch, check=True, capture_output=True, text=True)
    return diff.stdout


def _write_attempt_trace(trace_path: Path, request: AttemptRequest) -> None:
    """A minimal attempt trace: two model-call costs and one tool call."""
    with TraceWriter(trace_path) as writer:
        writer.write(
            TraceEvent(
                request.run_id,
                request.workflow_id,
                "runtime",
                "run_started",
                "ok",
                {"task": request.task.task_id},
                timestamp="2026-01-01T00:00:00+00:00",
            )
        )
        writer.write(
            TraceEvent(
                request.run_id,
                request.workflow_id,
                "budgets",
                "budget_updated",
                "ok",
                {"cost_usd": 0.01, "cumulative_cost_usd": 0.01},
                timestamp="2026-01-01T00:00:01+00:00",
            )
        )
        writer.write(
            TraceEvent(
                request.run_id,
                request.workflow_id,
                "runtime",
                "tool_requested",
                "ok",
                {"tool": "replace_text"},
                timestamp="2026-01-01T00:00:02+00:00",
            )
        )
        writer.write(
            TraceEvent(
                request.run_id,
                request.workflow_id,
                "budgets",
                "budget_updated",
                "ok",
                {"cost_usd": 0.02, "cumulative_cost_usd": 0.03},
                timestamp="2026-01-01T00:00:03+00:00",
            )
        )
        writer.write(
            TraceEvent(
                request.run_id,
                request.workflow_id,
                "runtime",
                "run_completed",
                "ok",
                {"status": "completed"},
                timestamp="2026-01-01T00:00:04+00:00",
            )
        )


def _grader_script(tmp_path: Path, name: str, exit_code: int) -> Path:
    script = tmp_path / f"grader-{name}.py"
    script.write_text(f"# grader {name}\nimport sys\nsys.exit({exit_code})\n", encoding="utf-8")
    return script


def _matrix(tasks: tuple[EvalTask, ...], repetitions: int = 1) -> EvalMatrix:
    return EvalMatrix(
        matrix_id="m-test",
        mode="scripted",
        tasks=tasks,
        configurations=(
            EvalConfiguration("cfg-a", "D", "config a"),
            EvalConfiguration("cfg-b", "D", "config b", "terse: {description}"),
        ),
        repetitions=repetitions,
    )


class _RecordingGrader:
    """A protocol-shaped grader that records every workdir it judged."""

    def __init__(self, grader_id: str, passed: bool | None = True) -> None:
        self.grader_id = grader_id
        self.version = "recording-v1"
        self.calls: list[Path] = []
        self._passed = passed

    def grade(self, workdir: Path) -> GraderResult:
        self.calls.append(workdir)
        if self._passed is None:
            return GraderResult(self.grader_id, self.version, None, 2, "", True)
        return GraderResult(
            self.grader_id, self.version, self._passed, 0 if self._passed else 1, "", False
        )


def test_full_matrix_is_recorded_with_configuration_and_repetitions(
    target_source: Path, tmp_path: Path
) -> None:
    patch = _patch_for(target_source, tmp_path)
    seen: list[AttemptRequest] = []

    def executor(request: AttemptRequest) -> AttemptOutcome:
        seen.append(request)
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(True, patch, "completed")

    tasks = (
        EvalTask("t1", "task one", "g1"),
        EvalTask("t2", "task two", "g2"),
    )
    graders: dict[str, Grader] = {"g1": _RecordingGrader("g1"), "g2": _RecordingGrader("g2")}
    runner = EvaluationRunner(
        _matrix(tasks, repetitions=2), target_source, tmp_path / "work", executor, graders
    )
    records = runner.run()

    assert len(records) == 8  # 2 tasks x 2 configs x 2 reps
    # Task-major matrix order with repetitions innermost, numbered from 1.
    assert [(r.task_id, r.config_id, r.repetition) for r in records] == [
        ("t1", "cfg-a", 1),
        ("t1", "cfg-a", 2),
        ("t1", "cfg-b", 1),
        ("t1", "cfg-b", 2),
        ("t2", "cfg-a", 1),
        ("t2", "cfg-a", 2),
        ("t2", "cfg-b", 1),
        ("t2", "cfg-b", 2),
    ]
    for record in records:
        # Required validation: configuration and mode recorded per run.
        assert record.baseline == "D"
        assert record.mode == "scripted"
        assert record.status == "completed" and record.graded_pass is True
        assert record.trace_ref == attempt_trace_filename(
            record.task_id, record.config_id, record.repetition
        )
        assert (tmp_path / "work" / "traces" / record.trace_ref).is_file()
    # The executor received the pinned identities and the rendered configuration.
    assert seen[0].run_id == eval_run_id("t1", "cfg-a", 1)
    assert seen[0].workflow_id == EVAL_WORKFLOW_ID
    assert seen[2].configuration.render_task(seen[2].task) == "terse: task one"


def test_every_run_gets_a_fresh_clone(target_source: Path, tmp_path: Path) -> None:
    patch = _patch_for(target_source, tmp_path)
    poisoned_views: list[bool] = []

    def executor(request: AttemptRequest) -> AttemptOutcome:
        # The dirty-clone probe: every attempt poisons its clone; if any later run
        # reused a clone, it would see the poison.
        poisoned_views.append((request.target_root / "poison.txt").exists())
        (request.target_root / "poison.txt").write_text("stale\n", encoding="utf-8")
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(True, patch, "completed")

    task = EvalTask("t1", "task one", "g1")
    grader = _RecordingGrader("g1")
    workdir = tmp_path / "work"
    # Pre-poison the clone destination: leftover state must be replaced, not trusted.
    stale = workdir / "clones" / "t1-cfg-a-r1"
    stale.mkdir(parents=True)
    (stale / "junk.txt").write_text("junk\n", encoding="utf-8")
    runner = EvaluationRunner(
        _matrix((task,), repetitions=3), target_source, workdir, executor, {"g1": grader}
    )
    records = runner.run()
    assert poisoned_views == [False] * 6  # 2 configs x 3 reps, all clean
    assert all(r.graded_pass is True for r in records)
    # Grading happened on ITS OWN fresh clone: the poison never reached the grader.
    for graded_dir in grader.calls:
        assert not (graded_dir / "poison.txt").exists()
        assert (graded_dir / "notes.txt").read_text(encoding="utf-8").startswith("baseline")


def test_grader_identity_and_version_are_recorded(target_source: Path, tmp_path: Path) -> None:
    patch = _patch_for(target_source, tmp_path)

    def executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(True, patch, "completed")

    grader_a = CommandGrader("g1", _grader_script(tmp_path, "a", 0), interpreter=(sys.executable,))
    grader_b = CommandGrader("g2", _grader_script(tmp_path, "b", 0), interpreter=(sys.executable,))
    tasks = (EvalTask("t1", "one", "g1"), EvalTask("t2", "two", "g2"))
    records = EvaluationRunner(
        _matrix(tasks), target_source, tmp_path / "work", executor, {"g1": grader_a, "g2": grader_b}
    ).run()
    by_task = {r.task_id: r for r in records if r.config_id == "cfg-a"}
    assert by_task["t1"].grader_id == "g1"
    assert by_task["t1"].grader_version == grader_a.version
    assert by_task["t2"].grader_version == grader_b.version
    # Different grader content, different recorded version.
    assert grader_a.version != grader_b.version


def test_grader_fail_is_an_implementation_failure(target_source: Path, tmp_path: Path) -> None:
    patch = _patch_for(target_source, tmp_path)

    def executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(True, patch, "completed")

    grader = _RecordingGrader("g1", passed=False)
    records = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work",
        executor,
        {"g1": grader},
    ).run()
    for record in records:
        assert record.status == "completed"
        assert record.graded_pass is False
        assert record.failure_class == "implementation failure"


def test_grader_infrastructure_error_is_never_a_task_failure(
    target_source: Path, tmp_path: Path
) -> None:
    patch = _patch_for(target_source, tmp_path)

    def executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(True, patch, "completed")

    grader = _RecordingGrader("g1", passed=None)  # grader exit 2
    records = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work",
        executor,
        {"g1": grader},
    ).run()
    for record in records:
        assert record.status == "infrastructure"
        assert record.graded_pass is None
        assert record.failure_class == "transient infrastructure failure"


def test_attempt_exceptions_are_classified_with_the_module7_taxonomy(
    target_source: Path, tmp_path: Path
) -> None:
    def timeout_executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        raise ModelTimeoutError("model call timed out after 60s", provider="scripted")

    grader = _RecordingGrader("g1")
    records = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work-timeout",
        timeout_executor,
        {"g1": grader},
    ).run()
    for record in records:
        # A provider fault is infrastructure, not evidence about the task.
        assert record.status == "infrastructure"
        assert record.failure_class == "model-provider failure"
        assert record.graded_pass is None
    assert grader.calls == []  # a crashed attempt is never graded

    def value_error_executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        raise ValueError("attempt-side bug")

    records = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work-value",
        value_error_executor,
        {"g1": grader},
    ).run()
    for record in records:
        # An unknown fault is a task-side failure, classified, still not graded.
        assert record.status == "failed"
        assert record.failure_class == "persistent unknown failure"


def test_replay_discipline_errors_are_reraised_not_recorded(
    target_source: Path, tmp_path: Path
) -> None:
    def executor(request: AttemptRequest) -> AttemptOutcome:
        raise ReplayExhaustedError("trace exhausted; the run diverged from its recording")

    runner = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work",
        executor,
        {"g1": _RecordingGrader("g1")},
    )
    # A replay mismatch is a harness-discipline bug, never an evaluation result.
    with pytest.raises(ReplayExhaustedError):
        runner.run()


def test_incomplete_attempt_is_failed_and_not_graded(target_source: Path, tmp_path: Path) -> None:
    def executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(False, None, "limit_exceeded")

    grader = _RecordingGrader("g1")
    records = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work",
        executor,
        {"g1": grader},
    ).run()
    for record in records:
        assert record.status == "failed"
        assert record.graded_pass is None
        assert record.failure_class == "implementation failure"
        assert record.patch_sha256 is None
    assert grader.calls == []


def test_unappliable_patch_is_infrastructure(target_source: Path, tmp_path: Path) -> None:
    def executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(True, "this is not a diff\n", "completed")

    grader = _RecordingGrader("g1")
    records = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work",
        executor,
        {"g1": grader},
    ).run()
    for record in records:
        assert record.status == "infrastructure"
        assert record.graded_pass is None
    assert grader.calls == []


def test_run_measures_come_from_the_attempt_trace(target_source: Path, tmp_path: Path) -> None:
    patch = _patch_for(target_source, tmp_path)

    def executor(request: AttemptRequest) -> AttemptOutcome:
        _write_attempt_trace(request.trace_path, request)
        return AttemptOutcome(True, patch, "completed")

    records = EvaluationRunner(
        _matrix((EvalTask("t1", "one", "g1"),)),
        target_source,
        tmp_path / "work",
        executor,
        {"g1": _RecordingGrader("g1")},
    ).run()
    for record in records:
        assert record.cost_usd == pytest.approx(0.03)
        assert record.tool_calls == 1
        assert record.duration_seconds == pytest.approx(4.0)
        assert record.patch_sha256 == patch_sha256(patch)
