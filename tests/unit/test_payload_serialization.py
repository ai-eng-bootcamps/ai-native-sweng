"""Unit tests for the trace payload serializers in models/types.py (spec 19).

These helpers define the JSON shape used in trace event payloads and script
files; the committed example trace and the replay adapter both depend on it.
"""

import json
from pathlib import Path

from anse_harness.models.types import (
    Message,
    ModelRequest,
    messages_from_payload,
    messages_to_payload,
    request_to_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TRACE = REPO_ROOT / "traces" / "examples" / "investigation-demo.jsonl"


def test_messages_round_trip() -> None:
    messages = [
        Message("system", "You are a read-only repository investigator."),
        Message("user", "Map the reservation lifecycle."),
        Message("assistant", "I will list files first."),
        Message("tool", "reservation.go", tool_call_id="call-1"),
    ]
    assert messages_from_payload(messages_to_payload(messages)) == messages


def test_request_payload_matches_committed_example_trace() -> None:
    with EXAMPLE_TRACE.open(encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    recorded = next(e for e in events if e["event_type"] == "model_requested")

    request = ModelRequest(
        messages=[
            Message("system", "You are a read-only repository investigator."),
            Message("user", "Map the reservation lifecycle in the bookit repository."),
        ]
    )
    assert request_to_payload(request) == recorded["payload"]["request"]
