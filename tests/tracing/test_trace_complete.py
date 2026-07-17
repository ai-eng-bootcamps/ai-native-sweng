"""The emitted trace carries the required model and tool events (spec Module 2, Lesson 2.5).

Reuses the supplied ``tracing/`` writer and reader; fails against the scaffolding
stubs and passes once the loop emits events to the reference behaviour.
"""

from pathlib import Path

from anse_harness.models import ScriptedAdapter
from anse_harness.runtime.loop import run_investigation
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.read_file import ReadFileTool
from anse_harness.tracing import TraceWriter, read_trace

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"
SCRIPT = FIXTURES / "read_file_investigation.script.json"
TASK = (FIXTURES / "task.txt").read_text(encoding="utf-8").strip()

REQUIRED_EVENTS = (
    "run_started",
    "model_requested",
    "model_responded",
    "tool_requested",
    "tool_completed",
    "state_transitioned",
    "run_completed",
)


def test_generated_trace_contains_required_events(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool(FIXTURE_REPO))
    trace_path = tmp_path / "run.jsonl"

    with TraceWriter(trace_path) as writer:
        run_investigation(TASK, ScriptedAdapter.from_file(SCRIPT), registry, tracer=writer)

    events = read_trace(trace_path)
    types = [e.event_type for e in events]
    for required in REQUIRED_EVENTS:
        assert required in types, f"missing {required}"

    # Each model response is paired with its request (the shape ReplayAdapter needs).
    request_ids = {e.event_id for e in events if e.event_type == "model_requested"}
    responded = [e for e in events if e.event_type == "model_responded"]
    assert responded, "no model_responded events"
    assert all(e.parent_event_id in request_ids for e in responded)

    # Exactly one read_file tool call was made and completed.
    assert types.count("tool_requested") == 1
    assert types.count("tool_completed") == 1
