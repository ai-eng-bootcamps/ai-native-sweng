"""End-to-end tests for the safe write run (Lessons 3.2-3.6).

A scripted model drives ``run_write_task`` against a throwaway target: the change is
made inside the sandbox worktree, judged by the validation pipeline, gated by approval,
and either surfaced as a patch or rolled back. Every failure scenario from the module
assessment ends with the worktree restored and the target untouched. These fail against
the scaffolding stubs and pass once the write runtime is implemented to the reference
behaviour.
"""

import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.models import (
    CostTable,
    ModelResponse,
    ScriptedAdapter,
    ScriptStep,
    ToolCall,
    Usage,
)
from anse_harness.policy.commands import CommandPolicyEngine
from anse_harness.runtime.sandbox import Sandbox, SandboxManager
from anse_harness.runtime.write_loop import WriteTaskResult, run_write_task
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
from anse_harness.tracing import TraceWriter, read_trace
from anse_harness.validation.pipeline import ValidationCheck, ValidationPipeline

pytestmark = pytest.mark.student_impl

TASK = "Replace the placeholder word in notes.txt and propose the change as a patch."


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """A throwaway target clone with one committed file."""
    repo = tmp_path / "target"
    repo.mkdir()
    (repo / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "base"],
    ):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)
    return repo


def _registry(worktree: Path, policy: CommandPolicyEngine, gate: ApprovalGate) -> ToolRegistry:
    """The write agent's canonical tool set, in deterministic registration order."""
    registry = ToolRegistry()
    registry.register(ListFilesTool(worktree))
    registry.register(SearchTextTool(worktree))
    registry.register(ReadFileTool(worktree))
    registry.register(InspectGitStatusTool(worktree))
    registry.register(CreateFileTool(worktree))
    registry.register(ReplaceTextTool(worktree))
    registry.register(DeleteFileTool(worktree, gate))
    registry.register(InspectDiffTool(worktree))
    registry.register(RunValidationCommandTool(worktree, policy))
    return registry


def _edit_then_answer() -> ScriptedAdapter:
    """A scripted model that makes one edit and then summarizes."""
    return ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="Editing the placeholder.",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="replace_text",
                            arguments={
                                "path": "notes.txt",
                                "old_text": "beta",
                                "new_text": "delta",
                            },
                        )
                    ],
                    stop_reason="tool_use",
                )
            ),
            ScriptStep(
                response=ModelResponse(
                    text="Replaced the placeholder in notes.txt; the change is ready.",
                    stop_reason="end_turn",
                )
            ),
        ]
    )


def _run(
    target: Path,
    adapter: ScriptedAdapter,
    *,
    approve: bool = True,
    checks: list[ValidationCheck] | None = None,
    max_iterations: int = 8,
    max_cost_usd: float | None = None,
    tracer: TraceWriter | None = None,
) -> tuple[Sandbox, WriteTaskResult]:
    policy = CommandPolicyEngine()
    gate = ApprovalGate(approve_all) if approve else ApprovalGate()
    manager = SandboxManager(target)
    sandbox = manager.create("write-test")
    pipeline = ValidationPipeline(
        sandbox.worktree,
        checks
        if checks is not None
        else [ValidationCheck("format-check", ("git", "diff", "--check"))],
        policy,
    )
    result = run_write_task(
        TASK,
        adapter,
        sandbox,
        _registry(sandbox.worktree, policy, gate),
        pipeline=pipeline,
        gate=gate,
        max_iterations=max_iterations,
        max_cost_usd=max_cost_usd,
        tracer=tracer,
    )
    return sandbox, result


# ─── the happy path: validated, approved, surfaced as a patch ────────────────────────
def test_validated_approved_change_becomes_a_patch(target: Path) -> None:
    sandbox, result = _run(target, _edit_then_answer())

    assert result.state.status is RunStatus.COMPLETED
    assert result.validation_report is not None and result.validation_report.ok
    assert result.patch is not None and "+delta" in result.patch
    assert result.rollback is None
    # The change exists ONLY in the sandbox; the target clone is untouched and there is
    # no merge: the patch is an artifact, not an applied change.
    assert (target / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
    assert (sandbox.worktree / "notes.txt").read_text(encoding="utf-8") == "alpha\ndelta\ngamma\n"


def test_rejected_approval_rolls_the_change_back(target: Path) -> None:
    sandbox, result = _run(target, _edit_then_answer(), approve=False)

    assert result.state.status is RunStatus.FAILED
    assert result.patch is None
    assert result.rollback is not None
    assert "notes.txt" in result.rollback.discarded_paths
    assert (sandbox.worktree / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"


def test_failed_validation_prevents_success_and_rolls_back(target: Path) -> None:
    failing = [ValidationCheck("must-fail", ("git", "show", "HEAD:absent.txt"))]
    sandbox, result = _run(target, _edit_then_answer(), checks=failing)

    assert result.state.status is RunStatus.FAILED
    assert result.validation_report is not None and not result.validation_report.ok
    assert result.approval is None  # validation failed; approval was never reached
    assert result.patch is None
    assert (sandbox.worktree / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"


# ─── assessment failure scenarios ────────────────────────────────────────────────────
def test_path_traversal_fails_the_run_and_rolls_back(target: Path, tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="Writing outside the sandbox.",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="create_file",
                            arguments={"path": "../../escaped.txt", "content": "gotcha"},
                        )
                    ],
                    stop_reason="tool_use",
                )
            )
        ]
    )
    _, result = _run(target, adapter)

    assert result.state.status is RunStatus.FAILED
    assert result.patch is None
    assert result.rollback is not None
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_prohibited_command_is_denied_and_visible_to_the_model(target: Path) -> None:
    adapter = ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="Trying to push.",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="run_validation_command",
                            arguments={"command": ["git", "push", "origin", "main"]},
                        )
                    ],
                    stop_reason="tool_use",
                )
            ),
            ScriptStep(
                response=ModelResponse(
                    text="Understood; pushing is denied. Nothing to change.",
                    stop_reason="end_turn",
                )
            ),
        ]
    )
    _, result = _run(target, adapter)

    denial = next(m for m in result.messages if m.role == "tool")
    assert "policy: deny" in denial.content
    # The denial is an observation, not a crash: the run still terminates cleanly.
    assert result.state.status is RunStatus.COMPLETED


def test_iteration_limit_rolls_back_partial_changes(target: Path) -> None:
    sandbox, result = _run(target, _edit_then_answer(), max_iterations=1)

    assert result.state.status is RunStatus.LIMIT_EXCEEDED
    assert result.patch is None
    assert result.rollback is not None
    assert "notes.txt" in result.rollback.discarded_paths
    assert (sandbox.worktree / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"


def test_cost_limit_escalates_and_rolls_back(target: Path) -> None:
    adapter = ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="Expensive edit.",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="replace_text",
                            arguments={
                                "path": "notes.txt",
                                "old_text": "beta",
                                "new_text": "delta",
                            },
                        )
                    ],
                    usage=Usage(input_tokens=1000, output_tokens=1000),
                    stop_reason="tool_use",
                )
            )
        ],
        cost_table=CostTable(input_usd_per_mtok=10.0, output_usd_per_mtok=10.0),
    )
    sandbox, result = _run(target, adapter, max_cost_usd=1e-9)

    assert result.state.status is RunStatus.ESCALATED
    assert result.patch is None
    assert result.rollback is not None
    assert (sandbox.worktree / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"


# ─── the write trace carries the Module 3 evidence ───────────────────────────────────
def test_write_trace_records_validation_approval_and_artifact(target: Path, tmp_path: Path) -> None:
    trace_path = tmp_path / "write-run.jsonl"
    with TraceWriter(trace_path) as writer:
        _run(target, _edit_then_answer(), max_cost_usd=1.0, tracer=writer)

    events = read_trace(trace_path)
    types = [e.event_type for e in events]
    for required in (
        "run_started",
        "context_packet_created",
        "model_requested",
        "model_responded",
        "tool_requested",
        "tool_completed",
        "budget_updated",
        "validation_started",
        "validation_completed",
        "approval_requested",
        "approval_resolved",
        "artifact_created",
        "state_transitioned",
        "run_completed",
    ):
        assert required in types, f"missing {required}"
    assert types[-1] == "run_completed"

    approval = next(e for e in events if e.event_type == "approval_resolved")
    assert approval.payload["decision"] == "approved"
    artifact = next(e for e in events if e.event_type == "artifact_created")
    assert artifact.payload["artifact_type"] == "patch"
