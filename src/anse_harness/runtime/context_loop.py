"""The context-driven model/tool loop (spec Module 4).

``run_context_investigation`` is Module 2's read-only loop with one change of input
discipline: instead of a bare task string and a pinned generic prompt, the run
consumes a CONTEXT PACKET. The system message is rendered from the packet's
instructions and the user message from its task, evidence, conflicts, and omissions -
so what the worker receives is exactly what the packet says it receives, and the
packet itself is recorded in the trace as a ``context_packet_created`` event before
the first model call.

Module 2's ``runtime/loop.py`` and Module 3's ``runtime/write_loop.py`` are untouched:
context-packet consumption lives entirely in this module and is engaged only by
calling it (the same opt-in pattern that kept the m02 traces byte-stable when Module 3
landed). The inner mechanics are deliberately the same loop - build a request, ask the
model, run the requested tool, fold the observation back, repeat until the model
answers or a limit stops it - and request construction stays byte-stable because
rendering is a pure function of the packet (see ``context/render.py``).

``models/`` and ``tracing/`` are SUPPLIED infrastructure. This module is SUPPLIED as
scaffolding for Module 4; see ``context/builder.py``.

SCAFFOLDING: implement ``run_context_investigation`` in Module 4, Lesson 4.4.
"""

from __future__ import annotations

from anse_harness.context.packet import ContextPacket
from anse_harness.models import ModelAdapter
from anse_harness.runtime.loop import InvestigationResult
from anse_harness.tools.base import ToolRegistry
from anse_harness.tracing import TraceWriter


def run_context_investigation(
    packet: ContextPacket,
    adapter: ModelAdapter,
    registry: ToolRegistry,
    *,
    max_iterations: int = 6,
    max_cost_usd: float | None = None,
    tracer: TraceWriter | None = None,
    run_id: str = "run-m04-context-investigation",
    workflow_id: str = "wf-context-investigation",
) -> InvestigationResult:
    """Run the model/tool loop with messages rendered from the context packet.

    Unlike Module 2's loop, the ``context_packet_created`` event is emitted on every
    traced run (not only budgeted ones) and carries the full packet payload: the
    packet IS this run's input, so the trace must record it.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.4: emit run_started (task id, worker type, packet id, "
        "revision) and context_packet_created (component 'context', payload "
        "packet.to_payload()); build the messages from render_system_prompt(packet) "
        "and render_user_prompt(packet); then run Module 2's loop mechanics "
        "unchanged - model call, tool execution, observation folding, iteration cap, "
        "and the max_cost_usd-gated budget events."
    )
