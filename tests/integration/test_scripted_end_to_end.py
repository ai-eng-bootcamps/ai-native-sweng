"""Integration smoke test: config file -> factory -> scripted conversation (spec 5.3)."""

from pathlib import Path

import pytest

from anse_harness.models import Message, ModelRequest, create_adapter_from_file

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "models" / "default.toml"


def test_scripted_conversation_end_to_end() -> None:
    adapter = create_adapter_from_file(DEFAULT_CONFIG)

    messages = [
        Message("system", "You are a read-only repository investigator."),
        Message("user", "Map the reservation lifecycle in the bookit repository."),
    ]
    first = adapter.complete(ModelRequest(messages=messages))
    assert first.stop_reason == "tool_use"
    (call,) = first.tool_calls
    assert call.name == "list_files"

    # Feed a deterministic tool result back, as the worker runtime will in Module 2.
    # The assistant turn is echoed with its tool call so history round-trips faithfully.
    messages = [
        *messages,
        first.to_message(),
        Message("tool", "reservation.go availability.go policy.go", tool_call_id=call.id),
    ]
    assert messages[-2].tool_calls == [call]
    second = adapter.complete(ModelRequest(messages=messages))
    assert second.stop_reason == "end_turn"
    assert "reservation.go" in second.text
    # The cost hook uses the cost table from the config file (5.0 / 25.0 USD per MTok).
    expected = (second.usage.input_tokens * 5.0 + second.usage.output_tokens * 25.0) / 1_000_000
    assert adapter.calculate_cost(second.usage) == pytest.approx(expected)
