"""Termination policy and no-progress detection for the review/fix loop (Lesson 6.8).

A review/fix loop must have deterministic termination rules (arch-ref 48): it COMPLETES
when no accepted findings remain, and it STOPS - with the residual findings escalated
to a human - when its iteration, cost, or worker budgets are exhausted or when it is
detectably not making progress. The system must not continue because a worker says
"try again".

No-progress detection (arch-ref 49) is a comparison of fingerprints, not judgment: the
orchestrator snapshots each iteration's integrated-patch hash and accepted-finding
keys, and a repeat of both is the no-progress signal - another iteration would spend
budget reproducing the same state.

This is deliberately the MINIMUM budget machinery Module 6 needs (spec 7.15 names more
budget types; the full controller belongs to the reliability module): the policy is a
frozen configuration record, the evaluator is a pure function over numbers the
workflow state already tracks, and nothing here is stateful.

SCAFFOLDING: the policy and snapshot contracts are supplied; implement
``detect_no_progress`` and ``decide_termination`` in Module 6, Lesson 6.8.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class TerminationPolicy:
    """The explicit limits under which the review/fix loop may continue (arch-ref 48)."""

    #: Maximum review iterations (a review + consolidation round counts as one).
    max_review_iterations: int = 2
    #: Monetary budget for the whole workflow, in USD; None disables the cost check.
    max_cost_usd: float | None = None
    #: Total worker-invocation budget; None disables the worker-count check.
    max_workers: int | None = None

    def describe(self) -> str:
        """One-line description recorded in the workflow state's policies block."""
        cost = "unbounded" if self.max_cost_usd is None else f"{self.max_cost_usd} USD"
        workers = "unbounded" if self.max_workers is None else str(self.max_workers)
        return (
            f"review/fix loop: max {self.max_review_iterations} review iterations, "
            f"cost budget {cost}, worker budget {workers}, no-progress detection; "
            "residual accepted findings escalate to a human"
        )


@dataclass(frozen=True)
class LoopSnapshot:
    """One iteration's progress fingerprint (arch-ref 49: what the detector compares)."""

    #: Fingerprint of the integrated patch after this iteration's consolidation.
    patch_fingerprint: str
    #: Sorted deduplication keys of the iteration's ACCEPTED findings.
    finding_keys: tuple[str, ...]


def patch_fingerprint(patch: str) -> str:
    """A stable fingerprint of one patch (SHA-256 of its exact bytes)."""
    return hashlib.sha256(patch.encode("utf-8")).hexdigest()


def detect_no_progress(previous: LoopSnapshot | None, current: LoopSnapshot) -> bool:
    """True when the loop provably reproduced the previous iteration (arch-ref 49).

    No progress means BOTH fingerprints repeat: the integrated patch is unchanged and
    the accepted findings carry the same deduplication keys - the fix iteration
    changed nothing and the reviewers found the same defects. The first iteration
    (``previous is None``) can never be no-progress.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.8: return False when previous is None; otherwise return "
        "whether both the patch fingerprint and the finding keys are identical to "
        "the previous snapshot's."
    )


def decide_termination(
    policy: TerminationPolicy,
    *,
    completed_iterations: int,
    cost_used: float,
    worker_count: int,
    no_progress: bool,
) -> str | None:
    """Decide whether the loop must stop despite accepted findings remaining.

    Called after a consolidation that produced accepted findings: ``None`` permits
    one more fix iteration; a reason string stops the loop (the orchestrator
    escalates with the residual findings). Checks run in a fixed order so the
    reported reason is deterministic: iterations, cost, workers, no-progress.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.8: return a reason string for the FIRST exhausted "
        "limit - completed_iterations >= max_review_iterations; cost_used >= "
        "max_cost_usd (when set); worker_count >= max_workers (when set); "
        "no_progress - and None when every check permits another iteration."
    )
