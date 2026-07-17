"""Execution state for a single investigation run (spec Module 2: state, termination).

The state carries just enough to make termination explicit and observable: how many tool
iterations have run, how much the run has cost, and which terminal condition (if any) the
run reached. Keeping this tiny is deliberate - the loop, not the state object, owns the
control flow; the state object only records where the loop got to.

Lesson 2.1 introduces the step count and the running/completed/failed/limit_exceeded
statuses. Lesson 2.4 adds the second, independent limit - a cost budget - and the
``escalated`` status: when the run exhausts its cost budget without an answer, it does not
silently stop, it escalates to a human who can decide whether to raise the budget.

SCAFFOLDING: the fields and status vocabulary are supplied; implement ``advance`` in
Module 2, Lesson 2.1 and ``charge`` in Module 2, Lesson 2.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunStatus(StrEnum):
    """The lifecycle status of one investigation run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    LIMIT_EXCEEDED = "limit_exceeded"
    ESCALATED = "escalated"


@dataclass
class ExecutionState:
    """Step count, cost, and status for one run, with the limits it must respect."""

    max_iterations: int
    #: Optional cost cap in USD. ``None`` means no cost limit is enforced (the Lesson 2.1
    #: minimal loop); a value engages the Lesson 2.4 cost budget.
    max_cost_usd: float | None = None
    step: int = 0
    cost_usd: float = 0.0
    status: RunStatus = RunStatus.RUNNING

    def advance(self) -> bool:
        """Record one completed tool iteration.

        Returns ``True`` when the iteration cap has now been reached, in which case the
        status transitions to ``LIMIT_EXCEEDED`` and the loop must stop.
        """
        raise NotImplementedError(
            "Module 2, Lesson 2.1: increment step; if step >= max_iterations, set "
            "status = RunStatus.LIMIT_EXCEEDED and return True, else return False."
        )

    def charge(self, cost_usd: float) -> bool:
        """Add the cost of one model call and enforce the cost budget.

        Returns ``True`` when the cost budget is now exhausted, in which case the status
        transitions to ``ESCALATED`` (the run hands off to a human rather than stopping
        silently) and the loop must stop.
        """
        raise NotImplementedError(
            "Module 2, Lesson 2.4: add cost_usd to self.cost_usd; if max_cost_usd is set and "
            "cost_usd >= max_cost_usd, set status = RunStatus.ESCALATED and return True, else "
            "return False."
        )
