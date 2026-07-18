"""Replay conformance for the safe write run (Module 3).

The recorded write task - read, edit, a policy-denied formatter run, diff inspection, an
approved validation command, then the summary - is driven by the real ``ReplayAdapter``
over ``traces/m03/write_task.jsonl``. A clean replay proves request construction stays
byte-stable while the loop folds edit results, policy denials, and a unified diff back
into the conversation, exactly as Module 2's conformance tests prove it for read-only
observations.

The Module 3 fixture tree is materialized into a real one-commit git repository first
(a ``.git`` directory cannot be committed as a fixture); the identity and date are
pinned so the repository is identical on every machine. This must stay in lockstep with
the reference trace-generation entry point.

These fail against the scaffolding stubs and pass once the sandbox, tools, policy,
pipeline, gate, and write loop are implemented to the reference behaviour.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.models import ReplayAdapter
from anse_harness.policy.commands import CommandPolicyEngine
from anse_harness.runtime import write_loop
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
from anse_harness.validation.pipeline import ValidationCheck, ValidationPipeline

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m03"
TASK = (FIXTURES / "write_task.task.txt").read_text(encoding="utf-8").strip()
TRACE = Path(__file__).resolve().parents[2] / "traces" / "m03" / "write_task.jsonl"

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


def _registry(worktree: Path, policy: CommandPolicyEngine, gate: ApprovalGate) -> ToolRegistry:
    """The write agent's canonical tool set, in the recorded registration order."""
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


def test_write_loop_replays_recorded_trace_without_mismatch(tmp_path: Path) -> None:
    # The loop pins exactly this prompt; the fixture ships it so a student build can
    # reproduce the recorded request. If either drifts, replay would mismatch.
    shipped = (FIXTURES / "write_system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
    assert shipped == write_loop.WRITE_SYSTEM_PROMPT

    repo = _materialize_fixture_repo(tmp_path)
    policy = CommandPolicyEngine()
    gate = ApprovalGate(approve_all)
    manager = SandboxManager(repo)
    sandbox = manager.create("m03-write-task")
    pipeline = ValidationPipeline(
        sandbox.worktree,
        [ValidationCheck("format-check", ("git", "diff", "--check"))],
        policy,
    )

    result = run_write_task(
        TASK,
        ReplayAdapter(TRACE),
        sandbox,
        _registry(sandbox.worktree, policy, gate),
        pipeline=pipeline,
        gate=gate,
        max_cost_usd=1.0,
    )

    assert result.state.status is RunStatus.COMPLETED
    # read, edit, denied formatter, diff, validation command: five tool iterations.
    assert result.state.step == 5
    assert result.validation_report is not None and result.validation_report.ok
    assert result.patch is not None
    assert "strings.ToLower(strings.TrimSpace(email))" in result.patch
    assert "internal/booking/holder.go" in result.answer
