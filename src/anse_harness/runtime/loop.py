"""The model/tool execution loop for a read-only investigation (spec Module 2).

The loop is the mechanism under every agent framework: build a request, ask the model,
and if the model asked for a tool, run it, fold the observation back into the
conversation, and ask again - until the model answers or a limit stops it. It is
intentionally small and explicit so every model call, tool call, observation, and state
transition is visible in the trace.

Two things are PINNED so that request construction is byte-stable across runs, which is
what lets a recorded trace replay with no mismatch:

* ``SYSTEM_PROMPT`` is a module-level constant, not built per run.
* the tool list comes from the registry in deterministic registration order.

Lesson 2.1 builds the minimal loop (``max_cost_usd=None``): input, model call, tool call,
observation, iteration cap. Lessons 2.4 and 2.5 add the full runtime on top, engaged by
passing a cost budget: a ``context_packet_created`` event that records the run's inputs, a
``budget_updated`` event per model call carrying cost and duration, a cost budget that
escalates when exhausted, and the resulting ``escalation_created`` event. With no budget,
the loop behaves exactly as it did in Lesson 2.1.

``models/`` and ``tracing/`` are SUPPLIED infrastructure - the loop consumes the adapter
interface and the trace writer; it does not reimplement provider plumbing.

SCAFFOLDING: ``SYSTEM_PROMPT`` and the result type are supplied; implement
``run_investigation`` in Module 2 (the minimal loop in Lesson 2.1, the cost budget,
escalation, and the context/budget trace events in Lessons 2.4-2.5).
"""

from __future__ import annotations

from dataclasses import dataclass

from anse_harness.models import Message, ModelAdapter
from anse_harness.state.state import ExecutionState
from anse_harness.tools.base import ToolRegistry
from anse_harness.tracing import TraceWriter

#: Pinned system prompt. Building this per run (e.g. embedding a timestamp) would change
#: the recorded request and break replay - see Lesson 2.1, Failure Scenario.
SYSTEM_PROMPT = (
    "You are a read-only repository investigator for the bookit platform. "
    "Investigate the repository using only the supplied read-only tools; you never "
    "modify it. Call one tool at a time and use each observation to decide your next "
    "step. When you have enough evidence, stop and give a concise answer that cites "
    "the files you relied on."
)


@dataclass(frozen=True)
class InvestigationResult:
    """The outcome of one investigation run: the answer, the final state, and history."""

    answer: str
    state: ExecutionState
    messages: list[Message]


def run_investigation(
    task: str,
    adapter: ModelAdapter,
    registry: ToolRegistry,
    *,
    max_iterations: int = 6,
    max_cost_usd: float | None = None,
    tracer: TraceWriter | None = None,
    run_id: str = "run-m02-read-file",
    workflow_id: str = "wf-read-file-investigation",
) -> InvestigationResult:
    """Run the model/tool loop until the model answers or a limit stops it."""
    raise NotImplementedError(
        "Module 2, Lesson 2.1: build a ModelRequest from the pinned SYSTEM_PROMPT, the task, "
        "and registry.specs(); call adapter.complete(); if the response has tool calls, run "
        "them via the registry, fold each observation back as a tool message, count the "
        "iteration with ExecutionState.advance(), and stop on a no-tool answer or the iteration "
        "cap. Emit trace events throughout. Lessons 2.4-2.5: when max_cost_usd is set, emit a "
        "context_packet_created event, charge each call with ExecutionState.charge() while "
        "recording a budget_updated event (cost + duration), and escalate (escalation_created) "
        "when the cost budget is exhausted."
    )
