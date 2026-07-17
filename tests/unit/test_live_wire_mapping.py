"""Unit tests for the live adapters' history wire mapping (spec 7.1: tool-call representation).

The mapping functions are pure translation logic with lazy SDK imports at the
module level, so these tests run offline with no provider SDKs installed.
"""

from __future__ import annotations

import json
from typing import Any

from anse_harness.models.live_anthropic import _split_messages
from anse_harness.models.live_gemini import _to_contents
from anse_harness.models.live_openai import _to_wire
from anse_harness.models.types import Message, ToolCall

LIST_FILES_CALL = ToolCall(id="call-1", name="list_files", arguments={"path": "src"})

HISTORY = [
    Message("system", "You are a helper."),
    Message("user", "List the files."),
    Message("assistant", "Listing now.", tool_calls=[LIST_FILES_CALL]),
    Message("tool", "a.py b.py", tool_call_id="call-1"),
    Message("assistant", "Two files found."),
]


TOOL_USE_BLOCK = {
    "type": "tool_use",
    "id": "call-1",
    "name": "list_files",
    "input": {"path": "src"},
}


def test_anthropic_history_mapping() -> None:
    system, wire = _split_messages(HISTORY)
    assert system == "You are a helper."
    assert wire == [
        {"role": "user", "content": "List the files."},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Listing now."},
                TOOL_USE_BLOCK,
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "a.py b.py"}],
        },
        {"role": "assistant", "content": "Two files found."},
    ]


def test_anthropic_omits_empty_text_block_on_tool_call_turn() -> None:
    _, wire = _split_messages([Message("assistant", "", tool_calls=[LIST_FILES_CALL])])
    assert wire == [{"role": "assistant", "content": [TOOL_USE_BLOCK]}]


def test_openai_history_mapping() -> None:
    wire = _to_wire(HISTORY)
    assert wire == [
        {"role": "system", "content": "You are a helper."},
        {"role": "user", "content": "List the files."},
        {
            "role": "assistant",
            "content": "Listing now.",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "list_files", "arguments": json.dumps({"path": "src"})},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "a.py b.py"},
        {"role": "assistant", "content": "Two files found."},
    ]


def test_openai_maps_empty_tool_call_turn_content_to_none() -> None:
    (item,) = _to_wire([Message("assistant", "", tool_calls=[LIST_FILES_CALL])])
    assert item["content"] is None


class _Part:
    """Stand-in for google.genai.types.Part."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.function_call: dict[str, Any] | None = None
        self.function_response: dict[str, Any] | None = None

    @classmethod
    def from_function_call(cls, *, name: str, args: dict[str, Any]) -> _Part:
        part = cls()
        part.function_call = {"name": name, "args": args}
        return part

    @classmethod
    def from_function_response(cls, *, name: str, response: dict[str, Any]) -> _Part:
        part = cls()
        part.function_response = {"name": name, "response": response}
        return part


class _Content:
    """Stand-in for google.genai.types.Content."""

    def __init__(self, role: str, parts: list[_Part]) -> None:
        self.role = role
        self.parts = parts


class _FakeGenaiTypes:
    """Stand-in for the google.genai types module."""

    Content = _Content
    Part = _Part


def test_gemini_history_mapping() -> None:
    system, contents = _to_contents(_FakeGenaiTypes, HISTORY)
    assert system == "You are a helper."
    assert [c.role for c in contents] == ["user", "model", "user", "model"]

    assert contents[0].parts[0].text == "List the files."

    model_turn = contents[1]
    assert model_turn.parts[0].text == "Listing now."
    assert model_turn.parts[1].function_call == {"name": "list_files", "args": {"path": "src"}}

    # The function response must carry the function NAME, resolved from the
    # originating assistant tool call - not the neutral tool-call id.
    tool_turn = contents[2]
    assert tool_turn.parts[0].function_response == {
        "name": "list_files",
        "response": {"result": "a.py b.py"},
    }

    assert contents[3].parts[0].text == "Two files found."


COUNT_LINES_CALL = ToolCall(id="call-2", name="count_lines", arguments={"path": "a.py"})

COUNT_LINES_BLOCK = {
    "type": "tool_use",
    "id": "call-2",
    "name": "count_lines",
    "input": {"path": "a.py"},
}

PARALLEL_HISTORY = [
    Message("user", "List the files and count the lines."),
    Message("assistant", "", tool_calls=[LIST_FILES_CALL, COUNT_LINES_CALL]),
    Message("tool", "a.py b.py", tool_call_id="call-1"),
    Message("tool", "17", tool_call_id="call-2"),
]


def test_anthropic_groups_parallel_tool_results_into_one_user_message() -> None:
    _, wire = _split_messages(PARALLEL_HISTORY)
    assert wire == [
        {"role": "user", "content": "List the files and count the lines."},
        {
            "role": "assistant",
            "content": [TOOL_USE_BLOCK, COUNT_LINES_BLOCK],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "a.py b.py"},
                {"type": "tool_result", "tool_use_id": "call-2", "content": "17"},
            ],
        },
    ]


def test_openai_keeps_one_tool_message_per_parallel_result() -> None:
    wire = _to_wire(PARALLEL_HISTORY)
    assert [m["role"] for m in wire] == ["user", "assistant", "tool", "tool"]
    assert [m.get("tool_call_id") for m in wire[2:]] == ["call-1", "call-2"]


def test_gemini_groups_parallel_tool_results_into_one_turn() -> None:
    _, contents = _to_contents(_FakeGenaiTypes, PARALLEL_HISTORY)
    assert [c.role for c in contents] == ["user", "model", "user"]
    # One function_response part per call, in call order, resolved by id.
    assert [p.function_response for p in contents[2].parts] == [
        {"name": "list_files", "response": {"result": "a.py b.py"}},
        {"name": "count_lines", "response": {"result": "17"}},
    ]


def test_gemini_unmatched_tool_result_falls_back_to_generic_name() -> None:
    _, contents = _to_contents(
        _FakeGenaiTypes, [Message("tool", "output", tool_call_id="call-unknown")]
    )
    response = contents[0].parts[0].function_response
    assert response is not None
    assert response["name"] == "tool"
