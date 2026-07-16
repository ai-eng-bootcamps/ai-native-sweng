"""Live Anthropic adapter: the default live provider (spec 5.3, 21).

Thin, non-streaming implementation. The anthropic SDK is imported lazily so
scripted and replay modes work with no provider SDKs installed. Assistant
messages are passed as plain text; "tool" role messages are mapped to
tool_result content blocks.
"""

from __future__ import annotations

import json
from typing import Any

from anse_harness.models.adapter import ModelAdapter
from anse_harness.models.errors import (
    MissingProviderSDKError,
    ModelTimeoutError,
    ProviderError,
    classify_retryable_status,
)
from anse_harness.models.types import (
    CostTable,
    Message,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ToolCall,
    Usage,
)

ANTHROPIC_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_structured_output=True,
    context_limit=1_000_000,
    cost_class="high",
    latency_class="standard",
)


def _split_messages(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Split system messages out and map the rest to the Anthropic wire format."""
    system_parts: list[str] = []
    wire: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        elif m.role == "tool":
            wire.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id,
                            "content": m.content,
                        }
                    ],
                }
            )
        else:
            wire.append({"role": m.role, "content": m.content})
    return "\n\n".join(system_parts), wire


class AnthropicAdapter(ModelAdapter):
    """Live model mode against the Anthropic Messages API."""

    def __init__(
        self,
        model: str,
        cost_table: CostTable | None = None,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        super().__init__(cost_table)
        try:
            import anthropic
        except ImportError as exc:
            raise MissingProviderSDKError("anthropic", "anthropic") from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self._model = model
        self._capabilities = capabilities if capabilities is not None else ANTHROPIC_CAPABILITIES

    def complete(self, request: ModelRequest) -> ModelResponse:
        system, messages = _split_messages(request.messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "messages": messages,
            "timeout": request.timeout_seconds,
        }
        if system:
            kwargs["system"] = system
        if request.tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in request.tools
            ]
        if request.response_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": request.response_schema}
            }
        try:
            response = self._client.messages.create(**kwargs)
        except self._anthropic.APITimeoutError as exc:
            raise ModelTimeoutError(str(exc), provider="anthropic") from exc
        except self._anthropic.APIStatusError as exc:
            raise ProviderError(
                str(exc),
                provider="anthropic",
                retryable=classify_retryable_status(exc.status_code),
                status_code=exc.status_code,
            ) from exc
        except self._anthropic.APIConnectionError as exc:
            raise ProviderError(str(exc), provider="anthropic", retryable=True) from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))
        text = "".join(text_parts)
        structured: dict[str, Any] | None = None
        if request.response_schema is not None and text:
            structured = json.loads(text)
        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            structured_output=structured,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason or "end_turn",
        )

    def capabilities(self) -> ModelCapabilities:
        return self._capabilities
