"""Live Gemini adapter: fallback provider (spec 21).

Thin, non-streaming implementation over the google-genai SDK, imported lazily
so scripted and replay modes work with no provider SDKs installed. Assistant
messages map to the "model" role, with tool calls as function_call parts;
tool results are passed as function responses addressed by function name,
resolved from the originating assistant tool call, with consecutive results
grouped into a single turn as Gemini requires for parallel calls.
"""

from __future__ import annotations

import uuid
from typing import Any

from anse_harness.models.adapter import ModelAdapter
from anse_harness.models.errors import (
    MissingProviderSDKError,
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

GEMINI_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_structured_output=True,
    context_limit=1_000_000,
    cost_class="medium",
    latency_class="standard",
)


def _to_contents(types: Any, messages: list[Message]) -> tuple[str, list[Any]]:
    """Map messages to google-genai contents; `types` is the SDK's types module."""
    system_parts: list[str] = []
    contents: list[Any] = []
    call_names: dict[str, str] = {}
    tool_turn: Any = None  # user Content collecting the current run of tool results
    for m in messages:
        if m.role not in ("tool", "system"):  # system messages never enter contents
            tool_turn = None
        if m.role == "system":
            system_parts.append(m.content)
        elif m.role == "tool":
            name = call_names.get(m.tool_call_id or "", "tool")
            part = types.Part.from_function_response(name=name, response={"result": m.content})
            # Gemini requires all responses to one function-call turn in one turn.
            if tool_turn is None:
                tool_turn = types.Content(role="user", parts=[part])
                contents.append(tool_turn)
            else:
                tool_turn.parts.append(part)
        elif m.role == "assistant" and m.tool_calls:
            parts: list[Any] = []
            if m.content:
                parts.append(types.Part(text=m.content))
            for c in m.tool_calls:
                call_names[c.id] = c.name
                parts.append(types.Part.from_function_call(name=c.name, args=c.arguments))
            contents.append(types.Content(role="model", parts=parts))
        else:
            role = "model" if m.role == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=m.content)]))
    return "\n\n".join(system_parts), contents


class GeminiAdapter(ModelAdapter):
    """Live model mode against the Gemini API via google-genai."""

    def __init__(
        self,
        model: str,
        cost_table: CostTable | None = None,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        super().__init__(cost_table)
        try:
            from google import genai
        except ImportError as exc:
            raise MissingProviderSDKError("gemini", "google-genai") from exc
        self._genai = genai
        self._client = genai.Client()
        self._model = model
        self._capabilities = capabilities if capabilities is not None else GEMINI_CAPABILITIES

    def complete(self, request: ModelRequest) -> ModelResponse:
        types = self._genai.types
        system, contents = _to_contents(types, request.messages)
        config_kwargs: dict[str, Any] = {
            "max_output_tokens": request.max_tokens,
            "http_options": types.HttpOptions(timeout=int(request.timeout_seconds * 1000)),
        }
        if system:
            config_kwargs["system_instruction"] = system
        if request.tools:
            config_kwargs["tools"] = [
                types.Tool(
                    function_declarations=[
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.input_schema,
                        }
                        for t in request.tools
                    ]
                )
            ]
        if request.response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_json_schema"] = request.response_schema
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except self._genai.errors.APIError as exc:
            status_code = exc.code if isinstance(exc.code, int) else 0
            raise ProviderError(
                str(exc),
                provider="gemini",
                retryable=classify_retryable_status(status_code),
                status_code=status_code,
            ) from exc

        tool_calls: list[ToolCall] = []
        for call in response.function_calls or []:
            tool_calls.append(
                ToolCall(
                    id=call.id or uuid.uuid4().hex,
                    name=call.name or "",
                    arguments=dict(call.args or {}),
                )
            )
        text = response.text or ""
        structured: dict[str, Any] | None = None
        if request.response_schema is not None and text:
            import json

            structured = json.loads(text)
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        if tool_calls:
            stop_reason = "tool_use"
        elif finish_reason == types.FinishReason.MAX_TOKENS:
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"
        usage = response.usage_metadata
        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            structured_output=structured,
            usage=Usage(
                input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            ),
            stop_reason=stop_reason,
        )

    def capabilities(self) -> ModelCapabilities:
        return self._capabilities
