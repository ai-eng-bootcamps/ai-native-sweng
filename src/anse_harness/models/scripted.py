"""Scripted model mode: deterministic, predefined responses for tests (spec 5.3).

The scripted adapter returns responses from an in-memory script or a JSON
script file, in order. It fails loudly when the script is exhausted or when a
request does not match the expectation recorded for the next step, so tests
never silently drift from the conversation they were written for.

Script file format (JSON): a list of steps, each
    {"expect_substring": "<optional text>", "response": {<response payload>}}
where the response payload uses the shape defined in types.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from anse_harness.models.adapter import ModelAdapter
from anse_harness.models.errors import ScriptExhaustedError, ScriptMismatchError
from anse_harness.models.types import (
    CostTable,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    response_from_payload,
)

SCRIPTED_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_structured_output=True,
    context_limit=1_000_000,
    cost_class="free",
    latency_class="instant",
)


@dataclass(frozen=True)
class ScriptStep:
    """One scripted exchange: an optional expectation plus the canned response."""

    response: ModelResponse
    #: When set, the last message of the incoming request must contain this text.
    expect_substring: str | None = field(default=None)


class ScriptedAdapter(ModelAdapter):
    """Returns predefined responses in order; deterministic by construction."""

    def __init__(self, steps: list[ScriptStep], cost_table: CostTable | None = None) -> None:
        super().__init__(cost_table)
        self._steps = steps
        self._position = 0

    @classmethod
    def from_file(cls, path: Path, cost_table: CostTable | None = None) -> ScriptedAdapter:
        """Load a script from a JSON file (see module docstring for the format)."""
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError(f"script file {path} must contain a JSON list of steps")
        steps = [
            ScriptStep(
                response=response_from_payload(item["response"]),
                expect_substring=item.get("expect_substring"),
            )
            for item in raw
        ]
        return cls(steps, cost_table)

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self._position >= len(self._steps):
            raise ScriptExhaustedError(
                f"script exhausted after {len(self._steps)} responses; "
                f"received request {self._position + 1}"
            )
        step = self._steps[self._position]
        if step.expect_substring is not None:
            last = request.messages[-1].content if request.messages else ""
            if step.expect_substring not in last:
                raise ScriptMismatchError(
                    f"script step {self._position + 1} expected the last message to contain "
                    f"{step.expect_substring!r}, got {last!r}"
                )
        self._position += 1
        return step.response

    def capabilities(self) -> ModelCapabilities:
        return SCRIPTED_CAPABILITIES
