"""Replay conformance: the loop replays the recorded trace with no mismatch (Lesson 2.1).

This is the load-bearing pinning proof. The loop rebuilds each request from the
pinned ``SYSTEM_PROMPT``, the task, and the tool registry; the real
``ReplayAdapter`` checks those requests against ``traces/m02/`` and raises
``ReplayMismatchError`` on any drift. A clean replay proves request construction
is byte-stable across runs.

These fail against the scaffolding stubs and pass once the loop, registry, tool,
and state are implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.models import ReplayAdapter, ReplayMismatchError
from anse_harness.runtime import loop
from anse_harness.runtime.loop import run_investigation
from anse_harness.state.state import RunStatus
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.read_file import ReadFileTool

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"
TASK = (FIXTURES / "task.txt").read_text(encoding="utf-8").strip()
TRACE = Path(__file__).resolve().parents[2] / "traces" / "m02" / "read_file_investigation.jsonl"


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(FIXTURE_REPO))
    return registry


def test_loop_replays_recorded_trace_without_mismatch() -> None:
    # The loop pins exactly this prompt; the fixture ships it so a student build can
    # reproduce the recorded request. If either drifts, replay would mismatch.
    shipped_prompt = (FIXTURES / "system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
    assert shipped_prompt == loop.SYSTEM_PROMPT

    result = run_investigation(TASK, ReplayAdapter(TRACE), _registry())

    assert result.state.status is RunStatus.COMPLETED
    assert result.state.step == 1
    assert "pending -> confirmed -> completed" in result.answer


def test_unpinned_system_prompt_breaks_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    # Building the system prompt dynamically (here: appending text) changes the
    # recorded request, so the very first replayed call mismatches. This is why
    # request construction must be pinned.
    monkeypatch.setattr(loop, "SYSTEM_PROMPT", loop.SYSTEM_PROMPT + " Session opened just now.")
    with pytest.raises(ReplayMismatchError):
        run_investigation(TASK, ReplayAdapter(TRACE), _registry())
