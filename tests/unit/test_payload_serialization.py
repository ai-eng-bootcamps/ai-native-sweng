"""Unit tests for the trace payload serializers in models/types.py (spec 19).

These helpers define the JSON shape used in trace event payloads and script
files; the committed example trace and the replay adapter both depend on it.
"""

import json
from pathlib import Path

import pytest

from anse_harness.models.types import (
    Message,
    ModelRequest,
    ModelResponse,
    ToolCall,
    messages_from_payload,
    messages_to_payload,
    request_to_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TRACE = REPO_ROOT / "traces" / "examples" / "investigation-demo.jsonl"

LIST_FILES_CALL = ToolCall(id="call-1", name="list_files", arguments={"path": "internal/booking"})


def test_messages_round_trip() -> None:
    messages = [
        Message("system", "You are a read-only repository investigator."),
        Message("user", "Map the reservation lifecycle."),
        Message("assistant", "I will list files first.", tool_calls=[LIST_FILES_CALL]),
        Message("tool", "reservation.go", tool_call_id="call-1"),
        Message("assistant", "The lifecycle is pending -> confirmed."),
    ]
    assert messages_from_payload(messages_to_payload(messages)) == messages


def test_tool_calls_only_valid_on_assistant_messages() -> None:
    with pytest.raises(ValueError, match="assistant"):
        Message("user", "hello", tool_calls=[LIST_FILES_CALL])


def test_response_to_message_carries_tool_calls() -> None:
    response = ModelResponse(
        text="I will list files first.",
        tool_calls=[LIST_FILES_CALL],
        stop_reason="tool_use",
    )
    message = response.to_message()
    assert message == Message("assistant", "I will list files first.", tool_calls=[LIST_FILES_CALL])


def _recorded_requests() -> list[dict[str, object]]:
    with EXAMPLE_TRACE.open(encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    return [e["payload"]["request"] for e in events if e["event_type"] == "model_requested"]


def test_request_payload_matches_committed_example_trace() -> None:
    recorded = _recorded_requests()[0]
    request = ModelRequest(
        messages=[
            Message("system", "You are a read-only repository investigator."),
            Message("user", "Map the reservation lifecycle in the bookit repository."),
        ]
    )
    assert request_to_payload(request) == recorded


def test_tool_call_request_payload_matches_committed_example_trace() -> None:
    recorded = _recorded_requests()[1]
    request = ModelRequest(
        messages=[
            Message("system", "You are a read-only repository investigator."),
            Message("user", "Map the reservation lifecycle in the bookit repository."),
            Message(
                "assistant",
                "I will start by listing the booking package files.",
                tool_calls=[LIST_FILES_CALL],
            ),
            Message("tool", "reservation.go availability.go policy.go", tool_call_id="call-1"),
        ]
    )
    assert request_to_payload(request) == recorded
