"""The write-capable model/tool loop and its finalization phases (spec Module 3).

``run_write_task`` is Module 2's loop grown into a safe write run. The inner mechanics
are deliberately the same - build a request, ask the model, run the requested tool, fold
the observation back, repeat until the model answers or a limit stops it - but the run
is bracketed by the Module 3 controls:

* it operates on an isolated ``Sandbox`` worktree (Lesson 3.2), never on the target
  clone itself;
* the registry it is given carries the narrow edit tools and the policy-gated command
  tool (Lessons 3.3-3.4);
* after the model finishes, the change is judged, not trusted: the validation pipeline
  runs the target's own checks (Lesson 3.5);
* a validated change still stops at the approval boundary - a human decision on the
  diff and the validation report - before the patch artifact is surfaced;
* every path that does not end in an approved, validated patch ends in rollback
  (Lesson 3.6), restoring the starting revision while the trace is preserved.

The run can produce a patch; it cannot apply one anywhere. There is no merge and no
push - finalization beyond the patch artifact is a human action outside the harness.

Module 2's loop is untouched: write capability lives entirely in this module and is
engaged only by calling ``run_write_task`` with a sandbox and a write-tool registry.
Request construction is pinned exactly as in Module 2 (``WRITE_SYSTEM_PROMPT`` is a
module-level constant; the tool list comes from the registry in registration order), so
a recorded write run replays byte-stable. The cost budget, the context packet, and the
budget events are gated on ``max_cost_usd`` exactly as in Module 2.

``models/`` and ``tracing/`` are SUPPLIED infrastructure - the loop consumes the adapter
interface and the trace writer; it does not reimplement provider plumbing.

SCAFFOLDING: ``WRITE_SYSTEM_PROMPT`` and the result type are supplied; implement
``run_write_task`` across Module 3 (the sandboxed loop in Lessons 3.2-3.4, validation
and approval in Lesson 3.5, rollback in Lesson 3.6).
"""

from __future__ import annotations

from dataclasses import dataclass

from anse_harness.approvals.gate import ApprovalDecision, ApprovalGate
from anse_harness.models import Message, ModelAdapter
from anse_harness.runtime.sandbox import RollbackRecord, Sandbox
from anse_harness.state.state import ExecutionState
from anse_harness.tools.base import ToolRegistry
from anse_harness.tracing import TraceWriter
from anse_harness.validation.pipeline import ValidationPipeline, ValidationReport

#: Pinned system prompt for write runs. Building this per run would change the recorded
#: request and break replay - the Module 2 pinning discipline, unchanged.
WRITE_SYSTEM_PROMPT = (
    "You are a write-capable coding agent for the bookit platform, working inside an "
    "isolated sandbox worktree. Modify files only through the supplied edit tools, and "
    "run commands only through the policy-gated command tool; denied requests come back "
    "as observations you must adapt to. You cannot merge or push. Call one tool at a "
    "time, inspect your diff before finishing, and when your change is complete, stop "
    "and summarize the change you propose."
)


@dataclass(frozen=True)
class WriteTaskResult:
    """The outcome of one write run: what happened, and what (if anything) survived.

    ``patch`` is set only when the change passed validation AND was approved; every
    other terminal path sets ``rollback`` instead, and the worktree is back at its
    starting revision.
    """

    answer: str
    state: ExecutionState
    messages: list[Message]
    validation_report: ValidationReport | None
    approval: ApprovalDecision | None
    patch: str | None
    rollback: RollbackRecord | None


def run_write_task(
    task: str,
    adapter: ModelAdapter,
    sandbox: Sandbox,
    registry: ToolRegistry,
    *,
    pipeline: ValidationPipeline,
    gate: ApprovalGate,
    max_iterations: int = 8,
    max_cost_usd: float | None = None,
    tracer: TraceWriter | None = None,
    run_id: str = "run-m03-write-task",
    workflow_id: str = "wf-safe-write-task",
) -> WriteTaskResult:
    """Run one bounded write task: loop, validate, seek approval, finalize or roll back."""
    raise NotImplementedError(
        "Module 3: run the Module 2 loop mechanics from the pinned WRITE_SYSTEM_PROMPT "
        "with the write-tool registry inside the sandbox (Lessons 3.2-3.4), then judge "
        "the change instead of trusting it: run the validation pipeline and record "
        "validation events; on success, request approval on the diff and validation "
        "report and record the decision; surface the patch artifact only when approved "
        "(Lesson 3.5); on every other path - tool failure, failed validation, rejected "
        "approval, iteration or cost limit - roll the sandbox back to its base revision "
        "and record the rollback record (Lesson 3.6)."
    )
