"""Model/tool loop under a scripted adapter: one tool call, folded observation, cap (Lesson 2.1).

These fail against the scaffolding stubs and pass once the loop, registry, tool,
and state are implemented to the reference behaviour in Module 2, Lesson 2.1.
"""

from pathlib import Path

from anse_harness.models import ModelResponse, ScriptedAdapter, ScriptStep, ToolCall, Usage
from anse_harness.runtime.loop import run_investigation
from anse_harness.state.state import RunStatus
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.read_file import ReadFileTool

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"
SCRIPT = FIXTURES / "read_file_investigation.script.json"
TASK = (FIXTURES / "task.txt").read_text(encoding="utf-8").strip()


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(FIXTURE_REPO))
    return registry


def test_scripted_loop_makes_one_read_file_call_and_terminates() -> None:
    adapter = ScriptedAdapter.from_file(SCRIPT)
    result = run_investigation(TASK, adapter, _registry())

    assert result.state.status is RunStatus.COMPLETED
    assert result.state.step == 1  # exactly one tool iteration
    assert [m.role for m in result.messages] == ["system", "user", "assistant", "tool"]

    tool_message = result.messages[-1]
    assert tool_message.tool_call_id == "call-1"
    assert "StatusConfirmed" in tool_message.content  # the folded observation
    assert "pending -> confirmed -> completed" in result.answer


def test_iteration_cap_stops_a_runaway_loop() -> None:
    # A model that always asks for another read must still be stopped by the cap.
    always_reads = ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="reading again",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="read_file",
                            arguments={"path": "internal/booking/reservation.go"},
                        )
                    ],
                    usage=Usage(input_tokens=1, output_tokens=1),
                    stop_reason="tool_use",
                )
            )
        ]
    )
    result = run_investigation(TASK, always_reads, _registry(), max_iterations=1)

    assert result.state.status is RunStatus.LIMIT_EXCEEDED
    assert result.state.step == 1
