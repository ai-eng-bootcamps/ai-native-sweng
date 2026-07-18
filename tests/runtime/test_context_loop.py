"""The context-driven loop under a scripted adapter (Module 4, Lesson 4.4).

These fail against the scaffolding stubs and pass once the repository intelligence,
builder, renders, and context loop are implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.context.builder import build_context_packet
from anse_harness.context.packet import ContextPacket
from anse_harness.context.render import render_system_prompt, render_user_prompt
from anse_harness.models import ModelResponse, ScriptedAdapter, ScriptStep, ToolCall, Usage
from anse_harness.runtime.context_loop import run_context_investigation
from anse_harness.state.state import RunStatus
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.read_file import ReadFileTool
from anse_harness.tracing import TraceWriter, read_trace

pytestmark = pytest.mark.student_impl

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "m04" / "repo"
PINNED_CLOCK = "2026-01-01T00:00:00+00:00"


def _packet() -> ContextPacket:
    return build_context_packet(
        FIXTURE_REPO,
        revision="rev-a",
        task_id="fx-hold-lifetime",
        task_description="Determine the hold lifetime the code enforces.",
        acceptance_criteria=("The enforced hold lifetime is identified with a file citation.",),
        token_budget=20000,
        search_terms=("hold", "expire"),
        conflict_topics=("minutes",),
        clock=lambda: PINNED_CLOCK,
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(FIXTURE_REPO))
    return registry


def _adapter() -> ScriptedAdapter:
    return ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="Confirming the enforced value in code.",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="read_file",
                            arguments={"path": "internal/booking/hold.go"},
                        )
                    ],
                    usage=Usage(input_tokens=1, output_tokens=1),
                    stop_reason="tool_use",
                ),
                expect_substring="Known instruction conflicts",
            ),
            ScriptStep(
                response=ModelResponse(
                    text="The code enforces a 30-minute hold via internal/booking/hold.go.",
                    tool_calls=[],
                    usage=Usage(input_tokens=1, output_tokens=1),
                    stop_reason="end_turn",
                ),
                expect_substring="const HoldTTLMinutes = 30",
            ),
        ]
    )


def test_loop_consumes_the_packet_as_its_messages() -> None:
    packet = _packet()
    result = run_context_investigation(packet, _adapter(), _registry())

    assert result.state.status is RunStatus.COMPLETED
    assert result.state.step == 1  # exactly one tool iteration
    assert result.messages[0].role == "system"
    assert result.messages[0].content == render_system_prompt(packet)
    assert result.messages[1].role == "user"
    assert result.messages[1].content == render_user_prompt(packet)
    assert "internal/booking/hold.go" in result.answer


def test_trace_records_the_packet_before_the_first_model_call(tmp_path: Path) -> None:
    packet = _packet()
    trace_path = tmp_path / "trace.jsonl"
    with TraceWriter(trace_path) as writer:
        run_context_investigation(packet, _adapter(), _registry(), tracer=writer)

    events = read_trace(trace_path)
    types = [event.event_type for event in events]
    assert types[0] == "run_started"
    # The packet is recorded on every traced run - no cost budget required - and
    # before any model_requested event.
    assert types[1] == "context_packet_created"
    assert "model_requested" in types
    packet_event = events[1]
    assert packet_event.component == "context"
    assert packet_event.payload["context_packet_id"] == packet.context_packet_id
    assert packet_event.payload["summary"]["token_estimate"] == packet.summary.token_estimate


def test_iteration_cap_still_bounds_the_context_loop() -> None:
    packet = _packet()
    always_reads = ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="reading again",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="read_file",
                            arguments={"path": "internal/booking/hold.go"},
                        )
                    ],
                    usage=Usage(input_tokens=1, output_tokens=1),
                    stop_reason="tool_use",
                )
            )
        ]
    )
    result = run_context_investigation(packet, always_reads, _registry(), max_iterations=1)
    assert result.state.status is RunStatus.LIMIT_EXCEEDED
    assert result.state.step == 1
