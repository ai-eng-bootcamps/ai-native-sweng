"""The evaluation runner: tasks x configurations x repetitions over fresh clones (spec 7.12).

One demonstration proves that something CAN happen; an evaluation measures what
HAPPENS. The runner turns the existing runtimes into a measurement instrument without
changing them: every attempt is executed by a caller-supplied executor that wires an
UNCHANGED course runtime (the Module 3 bounded write agent, the Module 5 workflow
engine, the Module 6 orchestrator) with an adapter for the run's mode - scripted,
replay, or live. The runner owns everything around the attempt:

* the RESET discipline: every run gets a fresh ``git clone`` of the pinned target -
  state carried between runs is the fastest way to measure nothing;
* GRADING on a second fresh clone with the attempt's patch applied, through the one
  grader interface of ``graders.py``;
* the infrastructure-vs-task distinction (consuming Module 7's failure taxonomy): a
  crashed sandbox, an unreachable provider, or a grader that could not run is NOT
  evidence about the task, and is recorded as ``infrastructure`` so metrics can exclude
  it from pass-rate denominators;
* the ``RunRecord`` artifact per run: outcome, grade, failure class, attributed cost,
  duration, tool calls, grader identity AND version, configuration, mode, and the trace
  reference - the evidence a report is built from. Run-level evaluation bookkeeping
  lives HERE, in records and reports, not in new trace event types.

Mode honesty (the Lesson 8.5 doctrine): every record carries its execution mode. In
scripted and replay modes repetition is deterministic BY CONSTRUCTION - re-running
measures the harness, not the model - and downstream reporting must say so instead of
presenting identical repetitions as a measured distribution.

SCAFFOLDING: the matrix/record contracts, the clone helper, and the write-task executor
are supplied; implement ``EvaluationRunner.run`` in Module 8, Lessons 8.2-8.5.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.evaluation.graders import Grader
from anse_harness.models import ModelAdapter
from anse_harness.policy.commands import CommandPolicyEngine
from anse_harness.runtime.sandbox import SandboxManager
from anse_harness.runtime.write_loop import run_write_task
from anse_harness.state.state import RunStatus
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.create_file import CreateFileTool
from anse_harness.tools.delete_file import DeleteFileTool
from anse_harness.tools.inspect_diff import InspectDiffTool
from anse_harness.tools.inspect_git_status import InspectGitStatusTool
from anse_harness.tools.list_files import ListFilesTool
from anse_harness.tools.read_file import ReadFileTool
from anse_harness.tools.replace_text import ReplaceTextTool
from anse_harness.tools.run_validation_command import RunValidationCommandTool
from anse_harness.tools.search_text import SearchTextTool
from anse_harness.tracing import TraceWriter
from anse_harness.validation.pipeline import ValidationCheck, ValidationPipeline

#: Execution modes a run record may carry (Lesson 8.5: every metric knows its mode).
EVALUATION_MODES: tuple[str, ...] = ("scripted", "replay", "live")

#: Run-record statuses. ``infrastructure`` runs are excluded from pass-rate
#: denominators; they are evidence about the harness, not about the task.
RUN_STATUSES: tuple[str, ...] = ("completed", "failed", "infrastructure")

#: Canonical failure classes that mark a run as an infrastructure failure when an
#: attempt raises (Module 7 taxonomy: the environment or the provider, never the task).
INFRASTRUCTURE_CLASSES: tuple[str, ...] = (
    "transient infrastructure failure",
    "model-provider failure",
)


class EvaluationError(Exception):
    """The evaluation harness itself was misused or could not operate."""


@dataclass(frozen=True)
class EvalTask:
    """One task of an evaluation matrix.

    ``validation_commands`` are the attempt-side validation checks (the target's own
    toolchain) the executor runs on the sandbox worktree; ``grader_id`` names the
    grader the runner must apply. For course tasks both come from the manifest; for
    fixture matrices they are declared inline.
    """

    task_id: str
    description: str
    grader_id: str
    validation_commands: tuple[tuple[str, ...], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Serialize for matrix files."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "grader_id": self.grader_id,
            "validation_commands": [list(c) for c in self.validation_commands],
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> EvalTask:
        """Deserialize one matrix task payload."""
        return cls(
            task_id=str(data["task_id"]),
            description=str(data["description"]),
            grader_id=str(data["grader_id"]),
            validation_commands=tuple(
                tuple(str(part) for part in command)
                for command in data.get("validation_commands", [])
            ),
        )


@dataclass(frozen=True)
class EvalConfiguration:
    """One configuration under comparison (Lesson 8.7).

    ``prompt_template`` is the configuration's task rendering: ``{description}`` is
    replaced by the task description. Rendering is pinned here so a recorded matrix
    replays byte-stable - two configurations that differ only in wording ARE two
    different configurations, and the difference must be reproducible.
    """

    config_id: str
    baseline: str
    description: str
    prompt_template: str = "{description}"

    def render_task(self, task: EvalTask) -> str:
        """Render the task text this configuration sends to its executor."""
        return self.prompt_template.format(description=task.description)

    def to_payload(self) -> dict[str, Any]:
        """Serialize for matrix files."""
        return {
            "config_id": self.config_id,
            "baseline": self.baseline,
            "description": self.description,
            "prompt_template": self.prompt_template,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> EvalConfiguration:
        """Deserialize one matrix configuration payload."""
        return cls(
            config_id=str(data["config_id"]),
            baseline=str(data["baseline"]),
            description=str(data["description"]),
            prompt_template=str(data.get("prompt_template", "{description}")),
        )


@dataclass(frozen=True)
class EvalMatrix:
    """The full run matrix: tasks x configurations x repetitions, plus its mode."""

    matrix_id: str
    mode: str
    tasks: tuple[EvalTask, ...]
    configurations: tuple[EvalConfiguration, ...]
    repetitions: int

    def __post_init__(self) -> None:
        if self.mode not in EVALUATION_MODES:
            raise EvaluationError(f"unknown evaluation mode {self.mode!r}")
        if self.repetitions < 1:
            raise EvaluationError("repetitions must be at least 1")
        if not self.tasks or not self.configurations:
            raise EvaluationError("a matrix needs at least one task and one configuration")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the committed matrix file."""
        return {
            "matrix_id": self.matrix_id,
            "mode": self.mode,
            "tasks": [task.to_payload() for task in self.tasks],
            "configurations": [config.to_payload() for config in self.configurations],
            "repetitions": self.repetitions,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> EvalMatrix:
        """Deserialize one matrix payload."""
        return cls(
            matrix_id=str(data["matrix_id"]),
            mode=str(data["mode"]),
            tasks=tuple(EvalTask.from_payload(t) for t in data["tasks"]),
            configurations=tuple(EvalConfiguration.from_payload(c) for c in data["configurations"]),
            repetitions=int(data["repetitions"]),
        )

    @classmethod
    def from_file(cls, path: Path) -> EvalMatrix:
        """Load one committed matrix file."""
        return cls.from_payload(json.loads(path.read_text(encoding="utf-8")))


def attempt_trace_filename(task_id: str, config_id: str, repetition: int) -> str:
    """The pinned trace filename for one run of the matrix."""
    return f"{task_id}__{config_id}__r{repetition}.jsonl"


def eval_run_id(task_id: str, config_id: str, repetition: int) -> str:
    """The pinned run id for one run (it also names the sandbox branch in the trace)."""
    return f"run-eval-{task_id}-{config_id}-r{repetition}"


#: The pinned workflow id every evaluation attempt trace carries.
EVAL_WORKFLOW_ID = "wf-m08-eval"


@dataclass(frozen=True)
class AttemptRequest:
    """Everything an executor needs for one attempt of one run."""

    task: EvalTask
    configuration: EvalConfiguration
    repetition: int
    target_root: Path
    trace_path: Path
    run_id: str
    workflow_id: str


@dataclass(frozen=True)
class AttemptOutcome:
    """What one attempt produced, reduced to what the runner must judge."""

    completed: bool
    patch: str | None
    termination_reason: str | None


#: An attempt executor: wires one UNCHANGED course runtime for one run.
AttemptExecutor = Callable[[AttemptRequest], AttemptOutcome]


@dataclass(frozen=True)
class RunRecord:
    """The per-run evaluation artifact: one row of evidence (arch-ref 65).

    ``duration_seconds`` is derived from the run's trace timestamps, so a record
    rebuilt from a stored trace reproduces it exactly. ``patch_sha256`` fingerprints
    the surviving patch (None when no patch survived).
    """

    task_id: str
    config_id: str
    baseline: str
    repetition: int
    mode: str
    status: str
    graded_pass: bool | None
    failure_class: str | None
    grader_id: str
    grader_version: str
    cost_usd: float
    duration_seconds: float
    tool_calls: int
    patch_sha256: str | None
    trace_ref: str

    def __post_init__(self) -> None:
        if self.mode not in EVALUATION_MODES:
            raise EvaluationError(f"unknown evaluation mode {self.mode!r}")
        if self.status not in RUN_STATUSES:
            raise EvaluationError(f"unknown run status {self.status!r}")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the run-records artifact."""
        return {
            "task_id": self.task_id,
            "config_id": self.config_id,
            "baseline": self.baseline,
            "repetition": self.repetition,
            "mode": self.mode,
            "status": self.status,
            "graded_pass": self.graded_pass,
            "failure_class": self.failure_class,
            "grader_id": self.grader_id,
            "grader_version": self.grader_version,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
            "tool_calls": self.tool_calls,
            "patch_sha256": self.patch_sha256,
            "trace_ref": self.trace_ref,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> RunRecord:
        """Deserialize one run-record payload."""
        return cls(
            task_id=str(data["task_id"]),
            config_id=str(data["config_id"]),
            baseline=str(data["baseline"]),
            repetition=int(data["repetition"]),
            mode=str(data["mode"]),
            status=str(data["status"]),
            graded_pass=None if data["graded_pass"] is None else bool(data["graded_pass"]),
            failure_class=(None if data["failure_class"] is None else str(data["failure_class"])),
            grader_id=str(data["grader_id"]),
            grader_version=str(data["grader_version"]),
            cost_usd=float(data["cost_usd"]),
            duration_seconds=float(data["duration_seconds"]),
            tool_calls=int(data["tool_calls"]),
            patch_sha256=(None if data["patch_sha256"] is None else str(data["patch_sha256"])),
            trace_ref=str(data["trace_ref"]),
        )


def write_run_records(records: tuple[RunRecord, ...], path: Path) -> None:
    """Persist run records in the pinned artifact format (deterministic bytes)."""
    payload = {"records": [record.to_payload() for record in records]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_run_records(path: Path) -> tuple[RunRecord, ...]:
    """Load a run-records artifact."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(RunRecord.from_payload(entry) for entry in data["records"])


def patch_sha256(patch: str) -> str:
    """Fingerprint one patch for run records."""
    return hashlib.sha256(patch.encode("utf-8")).hexdigest()


def fresh_clone(source: Path, dest: Path) -> Path:
    """The reset discipline made executable: a pristine clone at ``dest``, always.

    Whatever is at ``dest`` - a poisoned previous clone, a half-deleted directory - is
    removed first; evaluation never trusts leftover state between runs.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", "-q", "--no-hardlinks", str(source), str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise EvaluationError(f"cloning {source} failed: {exc.stderr.strip()}") from exc
    return dest


def write_task_executor(
    adapter_factory: Callable[[AttemptRequest], ModelAdapter],
    *,
    max_iterations: int = 8,
    max_cost_usd: float = 1.0,
) -> AttemptExecutor:
    """A baseline-D executor over the UNCHANGED Module 3 bounded write agent.

    The wiring is pinned - canonical tool registration order, validation checks from
    the task declaration, approve-all gate, trace at the request's path - so a matrix
    recorded through this executor replays byte-stable through the same executor with
    a replay adapter factory. This is deliberately the only place the wiring exists;
    the reference CLI and the conformance suite both call it.
    """

    def execute(request: AttemptRequest) -> AttemptOutcome:
        policy = CommandPolicyEngine()
        gate = ApprovalGate(approve_all)
        manager = SandboxManager(request.target_root)
        sandbox = manager.create(request.run_id)
        try:
            registry = ToolRegistry()
            registry.register(ListFilesTool(sandbox.worktree))
            registry.register(SearchTextTool(sandbox.worktree))
            registry.register(ReadFileTool(sandbox.worktree))
            registry.register(InspectGitStatusTool(sandbox.worktree))
            registry.register(CreateFileTool(sandbox.worktree))
            registry.register(ReplaceTextTool(sandbox.worktree))
            registry.register(DeleteFileTool(sandbox.worktree, gate))
            registry.register(InspectDiffTool(sandbox.worktree))
            registry.register(RunValidationCommandTool(sandbox.worktree, policy))
            pipeline = ValidationPipeline(
                sandbox.worktree,
                [
                    ValidationCheck(f"check-{index}", command)
                    for index, command in enumerate(request.task.validation_commands, 1)
                ],
                policy,
            )
            with TraceWriter(request.trace_path) as tracer:
                result = run_write_task(
                    request.configuration.render_task(request.task),
                    adapter_factory(request),
                    sandbox,
                    registry,
                    pipeline=pipeline,
                    gate=gate,
                    max_iterations=max_iterations,
                    max_cost_usd=max_cost_usd,
                    tracer=tracer,
                    run_id=request.run_id,
                    workflow_id=request.workflow_id,
                )
        finally:
            manager.destroy(sandbox)
        return AttemptOutcome(
            completed=result.state.status is RunStatus.COMPLETED,
            patch=result.patch,
            termination_reason=result.state.status.value,
        )

    return execute


class EvaluationRunner:
    """Drives one matrix: fresh clone, attempt, grade, classify, record - per run."""

    def __init__(
        self,
        matrix: EvalMatrix,
        target_source: Path,
        workdir: Path,
        executor: AttemptExecutor,
        graders: Mapping[str, Grader],
    ) -> None:
        for task in matrix.tasks:
            if task.grader_id not in graders:
                raise EvaluationError(
                    f"task {task.task_id!r} declares grader {task.grader_id!r} "
                    "but no such grader was supplied"
                )
        self.matrix = matrix
        self.target_source = target_source
        self.workdir = workdir
        self.executor = executor
        self.graders = dict(graders)

    def run(self) -> tuple[RunRecord, ...]:
        """Execute the full matrix and return one RunRecord per run.

        Matrix order is task-major: for each task, for each configuration, for
        repetitions 1..N. Per run:

        1. RESET: ``fresh_clone`` the target into ``workdir/clones/<task>-<config>-r<n>``
           and point the attempt trace at ``workdir/traces/<attempt_trace_filename>``.
        2. ATTEMPT: call the executor. If it RAISES, classify the exception with
           Module 7's ``classify_exception``: a class in ``INFRASTRUCTURE_CLASSES``
           records status ``infrastructure``, any other class records status ``failed``;
           either way the canonical class is the record's ``failure_class`` and the run
           is NOT graded. Replay/script discipline errors are not caught - a replay
           mismatch is a harness bug, not an evaluation result.
        3. GRADE: when the attempt completed with a patch, ``fresh_clone`` a SECOND
           clone under ``workdir/grade/``, apply the patch with ``git apply``, and run
           the task's grader from that clone. Grader pass records status ``completed``
           with ``graded_pass`` True; grader fail records ``completed``/False with
           failure class ``implementation failure``; a grader infrastructure result (or
           a patch that does not apply) records status ``infrastructure`` with class
           ``transient infrastructure failure`` and ``graded_pass`` None.
        4. NO PATCH: an attempt that did not complete (or completed without a patch)
           records status ``failed``, ``graded_pass`` None, and failure class
           ``implementation failure``.
        5. RECORD: cost, duration, and tool calls come from the attempt trace (via
           ``metrics.attribute_costs`` per-call scope, ``metrics.trace_duration_seconds``
           and ``metrics.trace_tool_calls``); the record carries the configuration id,
           baseline, mode, grader id AND version, patch fingerprint, and the trace
           FILENAME (never a machine path) as ``trace_ref``.
        """
        raise NotImplementedError(
            "Module 8, Lessons 8.2-8.5: iterate matrix.tasks x matrix.configurations x "
            "repetitions in task-major order and execute steps 1-5 of the contract "
            "above for each run, returning the records as a tuple."
        )
