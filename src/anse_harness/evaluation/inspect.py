"""Structured trace inspection: the six questions of Lesson 8.6, answered from evidence.

A trace is only useful if it can answer questions faster than re-running the system.
The inspector reduces one run - possibly spread over a per-worker trace-file set - to
the six answers the lesson demands:

1. which context was used        -> ``context_packet_created`` events
2. which worker acted            -> ``worker_started``/``worker_completed``/``worker_failed``
3. which tools were called       -> ``tool_requested`` counts by tool name
4. where the result changed      -> ``artifact_created`` ids and ``state_transitioned`` steps
5. why the execution terminated  -> escalation/failure reasons, else the completion record
6. what the execution cost       -> ``budget_updated``, bucketed by budget scope

Everything here consumes the PUBLIC tracing surface (``read_trace``, ``TraceEvent``)
only - the inspector is a reader, never a participant, and it must work on any
committed or student-recorded trace without new event types.

Payload conventions are component-specific (transitions carry ``from``/``to``;
orchestrator budget aggregates carry ``worker_invocation_id``); the inspector reads
the conventions the committed traces establish rather than inventing a schema.

Wall-clock text: re-executed validation commands print timing (``go test`` emits
``0.006s``) into ``validation_completed`` payloads - and ONLY there; model messages
never contain it, which is why replay stays byte-exact at the request level. Trace
comparison across recordings must normalize that text; ``normalize_timing_text`` is
the pinned normalization.

SCAFFOLDING: the inspection contract, filters, and normalization are supplied;
implement ``inspect_run`` in Module 8, Lesson 8.6.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anse_harness.tracing import TraceEvent

#: Wall-clock text in command output: a seconds figure like ``0.006s`` or ``(0.00s)``.
TIMING_TEXT_RE = re.compile(r"\d+\.\d+s")

#: The replacement token; stable across recordings by construction.
TIMING_TEXT_TOKEN = "_TIME_s"


def normalize_timing_text(text: str) -> str:
    """Replace wall-clock seconds figures in command output with a stable token.

    ``ok pkg 0.006s`` and ``ok pkg 0.005s`` normalize to the same string; nothing else
    in the text is touched. Apply this to BOTH sides before comparing re-executed
    command output across recordings.
    """
    return TIMING_TEXT_RE.sub(TIMING_TEXT_TOKEN, text)


def normalize_check_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the timing text inside a validation event payload.

    Returns a copy of a ``validation_completed``/``validation_started`` payload with
    every check's ``output`` field passed through ``normalize_timing_text``; other
    payload fields are untouched.
    """
    normalized = dict(payload)
    checks = normalized.get("checks")
    if isinstance(checks, list):
        normalized["checks"] = [
            (
                {**check, "output": normalize_timing_text(check["output"])}
                if isinstance(check, dict) and isinstance(check.get("output"), str)
                else check
            )
            for check in checks
        ]
    return normalized


def filter_events(
    events: Sequence[TraceEvent],
    *,
    event_type: str | None = None,
    component: str | None = None,
    run_id: str | None = None,
) -> list[TraceEvent]:
    """Select events by type, component, and/or run id (all filters optional)."""
    return [
        event
        for event in events
        if (event_type is None or event.event_type == event_type)
        and (component is None or event.component == component)
        and (run_id is None or event.run_id == run_id)
    ]


@dataclass(frozen=True)
class RunInspection:
    """One run reduced to the six answers, plus the per-file census behind them."""

    files: tuple[tuple[str, int], ...]
    event_count: int
    context_packets: int
    workers: tuple[tuple[str, str], ...]
    tool_counts: tuple[tuple[str, int], ...]
    artifact_ids: tuple[str, ...]
    transitions: tuple[tuple[str | None, str | None], ...]
    termination: str | None
    per_call_cost_usd: float
    per_invocation_cost_usd: float

    def six_questions(self) -> dict[str, Any]:
        """The Lesson 8.6 answers as one payload."""
        return {
            "which_context": self.context_packets,
            "which_worker": [list(pair) for pair in self.workers],
            "which_tools": [list(pair) for pair in self.tool_counts],
            "where_result_changed": {
                "artifacts": list(self.artifact_ids),
                "transitions": [list(pair) for pair in self.transitions],
            },
            "why_terminated": self.termination,
            "what_it_cost_usd": self.per_call_cost_usd,
        }

    def render(self) -> str:
        """A deterministic text summary of the six answers."""
        lines = [
            f"Trace inspection ({len(self.files)} file(s), {self.event_count} events)",
            f"1. context packets used: {self.context_packets}",
            "2. workers acted: "
            + (
                ", ".join(f"{worker}({event})" for event, worker in self.workers) or "none recorded"
            ),
            "3. tools called: "
            + (", ".join(f"{name} x{count}" for name, count in self.tool_counts) or "none"),
            "4. result changed at: "
            + (", ".join(self.artifact_ids) or "no artifacts recorded")
            + (
                f"; transitions: {' -> '.join(str(t[1]) for t in self.transitions)}"
                if self.transitions
                else ""
            ),
            f"5. terminated because: {self.termination}",
            f"6. attributed model cost: {self.per_call_cost_usd:.6f} USD"
            + (
                f" (orchestrator aggregate {self.per_invocation_cost_usd:.6f} USD)"
                if self.per_invocation_cost_usd
                else ""
            ),
        ]
        return "\n".join(lines) + "\n"


def inspect_run(paths: Sequence[Path]) -> RunInspection:
    """Reduce one run's trace file set to a ``RunInspection``.

    Files are read in the given order. Conventions (from the committed trace sets):
    workers are identified by the ``worker_id`` payload field of ``worker_*`` events,
    falling back to the event's run id; tool names come from the ``tool`` payload field
    of ``tool_requested`` (falling back to ``name``); transitions read ``from``/``to``;
    termination is the ``reason`` (or ``termination_reason``) of an
    ``escalation_created`` or ``run_failed`` event when one exists, otherwise the
    ``termination_reason``/``reason`` of ``run_completed`` (default ``"completed"``);
    costs are bucketed by budget scope exactly as ``metrics.attribute_costs`` buckets
    them (``worker_invocation_id`` present = per-invocation aggregate).
    """
    raise NotImplementedError(
        "Module 8, Lesson 8.6: read_trace each path, build the per-file event census, "
        "and fold every event into the RunInspection fields following the conventions "
        "in the contract above; tool counts in first-seen order, workers and artifacts "
        "in event order, cost buckets split on worker_invocation_id."
    )
