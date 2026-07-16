"""Live OpenAI adapter: fallback provider (spec 21).

Thin, non-streaming implementation over the Chat Completions API. The openai
SDK is imported lazily so scripted and replay modes work with no provider
SDKs installed.
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

#: OpenAI finish_reason values mapped to the normalized stop reasons (types.py).
_STOP_REASONS = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "refusal",
}

OPENAI_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_structured_output=True,
    context_limit=400_000,
    cost_class="high",
    latency_class="standard",
)


def _to_wire(messages: list[Message]) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        else:
            wire.append({"role": m.role, "content": m.content})
    return wire


class OpenAIAdapter(ModelAdapter):
    """Live model mode against the OpenAI Chat Completions API."""

    def __init__(
        self,
        model: str,
        cost_table: CostTable | None = None,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        super().__init__(cost_table)
        try:
            import openai
        except ImportError as exc:
            raise MissingProviderSDKError("openai", "openai") from exc
        self._openai = openai
        self._client = openai.OpenAI()
        self._model = model
        self._capabilities = capabilities if capabilities is not None else OPENAI_CAPABILITIES

    def complete(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _to_wire(request.messages),
            "max_completion_tokens": request.max_tokens,
            "timeout": request.timeout_seconds,
        }
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in request.tools
            ]
        if request.response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": request.response_schema},
            }
        try:
            response = self._client.chat.completions.create(**kwargs)
        except self._openai.APITimeoutError as exc:
            raise ModelTimeoutError(str(exc), provider="openai") from exc
        except self._openai.APIStatusError as exc:
            raise ProviderError(
                str(exc),
                provider="openai",
                retryable=classify_retryable_status(exc.status_code),
                status_code=exc.status_code,
            ) from exc
        except self._openai.APIConnectionError as exc:
            raise ProviderError(str(exc), provider="openai", retryable=True) from exc

        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls: list[ToolCall] = []
        for call in choice.message.tool_calls or []:
            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=json.loads(call.function.arguments),
                )
            )
        structured: dict[str, Any] | None = None
        if request.response_schema is not None and text:
            structured = json.loads(text)
        usage = response.usage
        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            structured_output=structured,
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            stop_reason=(
                "tool_use"
                if tool_calls
                else _STOP_REASONS.get(choice.finish_reason or "", "end_turn")
            ),
        )

    def capabilities(self) -> ModelCapabilities:
        return self._capabilities
