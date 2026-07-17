"""Replay conformance for the multi-tool investigation (Lessons 2.3-2.5).

The full read-only investigation - list_files, then search_text, then read_file, then an
answer - is driven by the real ``ReplayAdapter`` over the recorded trace
``traces/m02/investigation_multitool.jsonl``. A clean replay proves that request
construction stays byte-stable even as the loop folds several different tools'
observations back into the conversation.

These fail against the scaffolding stubs and pass once the tools, state, and loop are
implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.models import ReplayAdapter
from anse_harness.runtime.loop import run_investigation
from anse_harness.state.state import RunStatus
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.inspect_git_status import InspectGitStatusTool
from anse_harness.tools.list_files import ListFilesTool
from anse_harness.tools.read_file import ReadFileTool
from anse_harness.tools.run_read_only_command import RunReadOnlyCommandTool
from anse_harness.tools.search_text import SearchTextTool

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"
TASK = (FIXTURES / "investigation.task.txt").read_text(encoding="utf-8").strip()
TRACE = Path(__file__).resolve().parents[2] / "traces" / "m02" / "investigation_multitool.jsonl"


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ListFilesTool(FIXTURE_REPO))
    registry.register(SearchTextTool(FIXTURE_REPO))
    registry.register(ReadFileTool(FIXTURE_REPO))
    registry.register(InspectGitStatusTool(FIXTURE_REPO))
    registry.register(RunReadOnlyCommandTool(FIXTURE_REPO))
    return registry


def test_multitool_loop_replays_recorded_trace_without_mismatch() -> None:
    result = run_investigation(TASK, ReplayAdapter(TRACE), _registry(), max_cost_usd=1.0)

    assert result.state.status is RunStatus.COMPLETED
    assert result.state.step == 3  # list_files, search_text, read_file
    assert "internal/booking/lifecycle.go" in result.answer
    assert "lifecycle_test.go" in result.answer
