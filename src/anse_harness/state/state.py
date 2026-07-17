"""Minimal execution state for a single investigation run (spec Module 2: state, termination).

The state carries just enough to make termination explicit and observable: how
many tool iterations have run, and which terminal condition (if any) the run
reached. Keeping this tiny is deliberate - the loop, not the state object, owns
the control flow; the state object only records where the loop got to.

SCAFFOLDING: the fields and status vocabulary are supplied; implement ``advance``
in Module 2, Lesson 2.1.
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


@dataclass
class ExecutionState:
    """Step count and status for one run, with the iteration cap it must respect."""

    max_iterations: int
    step: int = 0
    status: RunStatus = RunStatus.RUNNING

    def advance(self) -> bool:
        """Record one completed tool iteration.

        Returns ``True`` when the iteration cap has now been reached, in which
        case the status transitions to ``LIMIT_EXCEEDED`` and the loop must stop.
        """
        raise NotImplementedError(
            "Module 2, Lesson 2.1: increment step; if step >= max_iterations, set "
            "status = RunStatus.LIMIT_EXCEEDED and return True, else return False."
        )
