"""Replay tests: ReplayAdapter against the committed example trace (spec 5.3, 7.16)."""

from pathlib import Path

import pytest

from anse_harness.models import (
    Message,
    ModelRequest,
    ReplayAdapter,
    ReplayExhaustedError,
    ReplayMismatchError,
    ToolCall,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TRACE = REPO_ROOT / "traces" / "examples" / "investigation-demo.jsonl"


def _first_request() -> ModelRequest:
    return ModelRequest(
        messages=[
            Message("system", "You are a read-only repository investigator."),
            Message("user", "Map the reservation lifecycle in the bookit repository."),
        ]
    )


def _second_request() -> ModelRequest:
    first = _first_request()
    return ModelRequest(
        messages=[
            *first.messages,
            Message(
                "assistant",
                "I will start by listing the booking package files.",
                tool_calls=[
                    ToolCall(id="call-1", name="list_files", arguments={"path": "internal/booking"})
                ],
            ),
            Message("tool", "reservation.go availability.go policy.go", tool_call_id="call-1"),
        ]
    )


def test_replays_recorded_interactions_in_order() -> None:
    adapter = ReplayAdapter(EXAMPLE_TRACE)

    first = adapter.complete(_first_request())
    assert first.stop_reason == "tool_use"
    assert first.tool_calls[0].name == "list_files"
    assert first.tool_calls[0].arguments == {"path": "internal/booking"}
    assert first.usage.input_tokens == 42

    second = adapter.complete(_second_request())
    assert second.stop_reason == "end_turn"
    assert "pending -> confirmed -> completed" in second.text


def test_replayed_response_to_message_matches_recorded_history() -> None:
    adapter = ReplayAdapter(EXAMPLE_TRACE)
    first = adapter.complete(_first_request())
    # The assistant turn recorded in the trace is exactly the first response's history message.
    assert first.to_message() == _second_request().messages[2]


def test_request_mismatch_raises() -> None:
    adapter = ReplayAdapter(EXAMPLE_TRACE)
    with pytest.raises(ReplayMismatchError):
        adapter.complete(ModelRequest(messages=[Message("user", "something unrecorded")]))


def test_trace_exhaustion_raises() -> None:
    adapter = ReplayAdapter(EXAMPLE_TRACE)
    adapter.complete(_first_request())
    adapter.complete(_second_request())
    with pytest.raises(ReplayExhaustedError):
        adapter.complete(_second_request())
