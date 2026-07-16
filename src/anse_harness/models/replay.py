"""Replay model mode: re-serve captured model interactions from a trace (spec 5.3).

The replay adapter reads a JSONL trace file (spec 19 format, see
docs/trace-events.md) and replays its model interactions in order. An
interaction is a model_requested event paired with the model_responded event
whose parent_event_id points back to it. Incoming request messages must match
the recorded request; a mismatch or an extra request fails loudly so replayed
demonstrations and regression tests stay honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anse_harness.models.adapter import ModelAdapter
from anse_harness.models.errors import ReplayExhaustedError, ReplayMismatchError
from anse_harness.models.scripted import SCRIPTED_CAPABILITIES
from anse_harness.models.types import (
    CostTable,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    messages_to_payload,
    response_from_payload,
)
from anse_harness.tracing import TraceEvent, read_trace

REPLAY_CAPABILITIES = SCRIPTED_CAPABILITIES


@dataclass(frozen=True)
class _Interaction:
    recorded_messages: list[dict[str, object]]
    response: ModelResponse


def _pair_interactions(events: list[TraceEvent]) -> list[_Interaction]:
    requests = {e.event_id: e for e in events if e.event_type == "model_requested"}
    interactions: list[_Interaction] = []
    for event in events:
        if event.event_type != "model_responded":
            continue
        if event.parent_event_id is None or event.parent_event_id not in requests:
            raise ValueError(
                f"model_responded event {event.event_id} has no matching model_requested parent"
            )
        request_event = requests[event.parent_event_id]
        request_payload = request_event.payload.get("request", {})
        response_payload = event.payload.get("response", {})
        interactions.append(
            _Interaction(
                recorded_messages=list(request_payload.get("messages", [])),
                response=response_from_payload(dict(response_payload)),
            )
        )
    return interactions


class ReplayAdapter(ModelAdapter):
    """Replays previously captured request/response interactions from a trace file."""

    def __init__(self, trace_path: Path, cost_table: CostTable | None = None) -> None:
        super().__init__(cost_table)
        self._trace_path = trace_path
        self._interactions = _pair_interactions(read_trace(trace_path))
        self._position = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self._position >= len(self._interactions):
            raise ReplayExhaustedError(
                f"trace {self._trace_path} contains {len(self._interactions)} model "
                f"interactions; received request {self._position + 1}"
            )
        interaction = self._interactions[self._position]
        incoming = [dict(m) for m in messages_to_payload(request.messages)]
        if incoming != interaction.recorded_messages:
            raise ReplayMismatchError(
                f"request {self._position + 1} does not match the recorded request in "
                f"{self._trace_path}: expected messages {interaction.recorded_messages!r}, "
                f"got {incoming!r}"
            )
        self._position += 1
        return interaction.response

    def capabilities(self) -> ModelCapabilities:
        return REPLAY_CAPABILITIES
