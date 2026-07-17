"""The full-runtime trace carries context, cost, and duration (Lesson 2.5, spec section 19).

The minimal Lesson 2.1 trace records input, model call, tool call, observation, and state
transition. With a cost budget engaged, the loop also records a context packet, and a
budget event per model call carrying cost and duration - the remaining section 19
categories. This fails against the scaffolding stubs and passes once the loop is
implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.models import CostTable, ScriptedAdapter
from anse_harness.runtime.loop import run_investigation
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.list_files import ListFilesTool
from anse_harness.tools.read_file import ReadFileTool
from anse_harness.tools.search_text import SearchTextTool
from anse_harness.tracing import TraceWriter, read_trace

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"
SCRIPT = FIXTURES / "investigation_multitool.script.json"
TASK = (FIXTURES / "investigation.task.txt").read_text(encoding="utf-8").strip()

REQUIRED_EVENTS = (
    "run_started",
    "context_packet_created",
    "model_requested",
    "model_responded",
    "tool_requested",
    "tool_completed",
    "budget_updated",
    "state_transitioned",
    "run_completed",
)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ListFilesTool(FIXTURE_REPO))
    registry.register(SearchTextTool(FIXTURE_REPO))
    registry.register(ReadFileTool(FIXTURE_REPO))
    return registry


def test_full_trace_records_context_cost_and_duration(tmp_path: Path) -> None:
    trace_path = tmp_path / "run.jsonl"
    adapter = ScriptedAdapter.from_file(
        SCRIPT, cost_table=CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)
    )
    with TraceWriter(trace_path) as writer:
        run_investigation(TASK, adapter, _registry(), max_cost_usd=1.0, tracer=writer)

    events = read_trace(trace_path)
    types = [e.event_type for e in events]
    for required in REQUIRED_EVENTS:
        assert required in types, f"missing {required}"

    # The context packet names the run's inputs (spec 19: input, context).
    context = next(e for e in events if e.event_type == "context_packet_created")
    assert context.payload["task"]
    assert "list_files" in context.payload["tools"]

    # Every model call is charged and timed (spec 19: cost, duration).
    budget_events = [e for e in events if e.event_type == "budget_updated"]
    assert budget_events
    for event in budget_events:
        assert "cost_usd" in event.payload
        assert "duration_ms" in event.payload
    assert types.count("budget_updated") == types.count("model_responded")
