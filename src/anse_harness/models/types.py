"""Provider-neutral request/response data model for the model adapter (spec 5.3, 7.1).

These types are the common currency between the harness and every model
execution mode (live, scripted, replay). Serialization helpers at the bottom
define the JSON shape used in trace event payloads (spec 19) and script files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Cost classes for capability metadata (spec 7.1).
COST_CLASSES = ("free", "low", "medium", "high")
#: Latency classes for capability metadata (spec 7.1).
LATENCY_CLASSES = ("instant", "fast", "standard", "slow")


@dataclass(frozen=True)
class Message:
    """One conversation message. Roles: "system", "user", "assistant", "tool"."""

    role: str
    content: str
    #: Set when role == "tool": the id of the tool call this message answers.
    tool_call_id: str | None = None
    #: Set when role == "assistant": the tool calls this message made.
    tool_calls: list[ToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.tool_calls and self.role != "assistant":
            raise ValueError(f"tool_calls are only valid on assistant messages, got {self.role!r}")


@dataclass(frozen=True)
class ToolSpec:
    """A tool made available to the model (name, description, JSON schema for inputs)."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    """Token usage reported for one model call."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class CostTable:
    """Per-model prices in USD per million tokens (spec 20: model cost table)."""

    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0

    def cost_usd(self, usage: Usage) -> float:
        """Compute the cost of one call in USD."""
        return (
            usage.input_tokens * self.input_usd_per_mtok
            + usage.output_tokens * self.output_usd_per_mtok
        ) / 1_000_000


@dataclass(frozen=True)
class ModelCapabilities:
    """Capability metadata exposed by an adapter (spec 7.1)."""

    supports_tools: bool
    supports_structured_output: bool
    context_limit: int
    cost_class: str
    latency_class: str


@dataclass(frozen=True)
class ModelRequest:
    """One model call: messages plus tools, structured-output schema, and limits."""

    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    #: JSON schema for structured output; None means free-form text.
    response_schema: dict[str, Any] | None = None
    max_tokens: int = 4096
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class ModelResponse:
    """The normalized result of one model call."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    #: Parsed structured output when the request set a response_schema.
    structured_output: dict[str, Any] | None = None
    usage: Usage = field(default_factory=lambda: Usage(0, 0))
    #: Normalized stop reason: "end_turn", "tool_use", "max_tokens", "refusal".
    stop_reason: str = "end_turn"

    def to_message(self) -> Message:
        """Convert to an assistant history message that carries this response's tool calls."""
        return Message(role="assistant", content=self.text, tool_calls=list(self.tool_calls))


def _tool_calls_to_payload(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in tool_calls]


def _tool_calls_from_payload(payload: list[dict[str, Any]]) -> list[ToolCall]:
    return [
        ToolCall(id=str(c["id"]), name=str(c["name"]), arguments=dict(c.get("arguments", {})))
        for c in payload
    ]


def messages_to_payload(messages: list[Message]) -> list[dict[str, Any]]:
    """Serialize messages for trace payloads and script files."""
    out: list[dict[str, Any]] = []
    for m in messages:
        item: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_call_id is not None:
            item["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            item["tool_calls"] = _tool_calls_to_payload(m.tool_calls)
        out.append(item)
    return out


def messages_from_payload(payload: list[dict[str, Any]]) -> list[Message]:
    """Deserialize messages from a trace payload or script file."""
    return [
        Message(
            role=str(item["role"]),
            content=str(item["content"]),
            tool_call_id=item.get("tool_call_id"),
            tool_calls=_tool_calls_from_payload(item.get("tool_calls", [])),
        )
        for item in payload
    ]


def request_to_payload(request: ModelRequest) -> dict[str, Any]:
    """Serialize a request for trace payloads (spec 19: model requested)."""
    return {
        "messages": messages_to_payload(request.messages),
        "tools": [t.name for t in request.tools],
        "response_schema": request.response_schema,
        "max_tokens": request.max_tokens,
    }


def response_to_payload(response: ModelResponse) -> dict[str, Any]:
    """Serialize a response for trace payloads (spec 19: model responded)."""
    return {
        "text": response.text,
        "tool_calls": _tool_calls_to_payload(response.tool_calls),
        "structured_output": response.structured_output,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "stop_reason": response.stop_reason,
    }


def response_from_payload(payload: dict[str, Any]) -> ModelResponse:
    """Deserialize a response from a trace payload or script file."""
    usage = payload.get("usage", {})
    return ModelResponse(
        text=str(payload.get("text", "")),
        tool_calls=_tool_calls_from_payload(payload.get("tool_calls", [])),
        structured_output=payload.get("structured_output"),
        usage=Usage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        ),
        stop_reason=str(payload.get("stop_reason", "end_turn")),
    )
