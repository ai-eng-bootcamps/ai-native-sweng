"""Replay conformance for the context-driven investigation (Module 4).

The recorded context run - a packet built over the pinned Module 4 fixture, a
symbol search, a file read, then the answer - is driven by the real ``ReplayAdapter``
over ``traces/m04/context_investigation.jsonl``. A clean replay proves that the whole
context path is deterministic end to end: instruction discovery, relevance scoring,
dependency and test evidence, conflict detection, budgeting, and prompt rendering all
reproduce the recorded requests byte for byte.

The Module 4 fixture tree is materialized into a real one-commit git repository with
the same pinned identity and date as Module 3's conformance test, so the revision
recorded inside the packet (and therefore inside the rendered prompts) is identical
on every machine. The packet's extraction timestamps are pinned too. Both must stay
in lockstep with the reference trace-generation entry point.

These fail against the scaffolding stubs and pass once the repository intelligence,
instruction layer, context builder, renders, and context loop are implemented to the
reference behaviour.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.context.builder import build_context_packet
from anse_harness.context.packet import ContextPacket
from anse_harness.context.render import render_system_prompt
from anse_harness.models import ReplayAdapter
from anse_harness.runtime.context_loop import run_context_investigation
from anse_harness.state.state import RunStatus
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.inspect_git_status import InspectGitStatusTool
from anse_harness.tools.list_files import ListFilesTool
from anse_harness.tools.read_file import ReadFileTool
from anse_harness.tools.run_read_only_command import RunReadOnlyCommandTool
from anse_harness.tools.search_text import SearchTextTool

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m04"
TRACE = Path(__file__).resolve().parents[2] / "traces" / "m04" / "context_investigation.jsonl"

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

#: Pinned extraction time for the recorded packet. Must match the reference entry point.
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


def _build_packet(repo: Path) -> ContextPacket:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    spec = json.loads((FIXTURES / "context_task.json").read_text(encoding="utf-8"))
    return build_context_packet(
        repo,
        revision=revision,
        task_id=spec["task_id"],
        task_description=spec["description"],
        acceptance_criteria=spec["acceptance_criteria"],
        worker_type=spec["worker_type"],
        token_budget=spec["token_budget"],
        search_terms=spec["search_terms"],
        conflict_topics=spec["conflict_topics"],
        clock=lambda: PINNED_CLOCK_ISO,
    )


def _registry(repo: Path) -> ToolRegistry:
    """The read-only tool set, in the recorded registration order."""
    registry = ToolRegistry()
    registry.register(ListFilesTool(repo))
    registry.register(SearchTextTool(repo))
    registry.register(ReadFileTool(repo))
    registry.register(InspectGitStatusTool(repo))
    registry.register(RunReadOnlyCommandTool(repo))
    return registry


def test_context_loop_replays_recorded_trace_without_mismatch(tmp_path: Path) -> None:
    repo = _materialize_fixture_repo(tmp_path)
    packet = _build_packet(repo)

    # The fixture ships the rendered system prompt of the recorded packet, so a
    # student build can spot rendering drift directly. If either drifts, replay
    # would mismatch.
    shipped = (FIXTURES / "context_system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
    assert render_system_prompt(packet) == shipped

    result = run_context_investigation(
        packet, ReplayAdapter(TRACE), _registry(repo), max_cost_usd=1.0
    )

    assert result.state.status is RunStatus.COMPLETED
    # search_text, read_file: two tool iterations before the answer.
    assert result.state.step == 2
    assert "internal/booking/hold.go" in result.answer
    assert "README.md" in result.answer
    assert "30" in result.answer
