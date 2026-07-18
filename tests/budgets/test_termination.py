"""Termination policy and no-progress detection (Module 6, Lesson 6.8).

Exercises the deterministic loop-termination rules (arch-ref 48) and the fingerprint
comparison behind no-progress detection (arch-ref 49). These fail against the
scaffolding stubs and pass once the policy evaluator is implemented to the reference
behaviour.
"""

import pytest

from anse_harness.budgets.policy import (
    LoopSnapshot,
    TerminationPolicy,
    decide_termination,
    detect_no_progress,
    patch_fingerprint,
)

pytestmark = pytest.mark.student_impl

SNAPSHOT = LoopSnapshot(patch_fingerprint=patch_fingerprint("diff"), finding_keys=("k1", "k2"))


def test_first_iteration_is_never_no_progress() -> None:
    assert detect_no_progress(None, SNAPSHOT) is False


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (SNAPSHOT, True),
        (
            LoopSnapshot(patch_fingerprint=patch_fingerprint("other"), finding_keys=("k1", "k2")),
            False,
        ),
        (
            LoopSnapshot(patch_fingerprint=patch_fingerprint("diff"), finding_keys=("k3",)),
            False,
        ),
    ],
)
def test_no_progress_requires_both_fingerprints_to_repeat(
    current: LoopSnapshot, expected: bool
) -> None:
    assert detect_no_progress(SNAPSHOT, current) is expected


def test_termination_permits_another_iteration_within_all_budgets() -> None:
    policy = TerminationPolicy(max_review_iterations=3, max_cost_usd=1.0, max_workers=20)
    assert (
        decide_termination(
            policy, completed_iterations=1, cost_used=0.1, worker_count=8, no_progress=False
        )
        is None
    )


def test_termination_stops_at_max_iterations() -> None:
    reason = decide_termination(
        TerminationPolicy(max_review_iterations=2),
        completed_iterations=2,
        cost_used=0.0,
        worker_count=0,
        no_progress=False,
    )
    assert reason is not None and "maximum review iterations" in reason


def test_termination_stops_at_cost_and_worker_budgets() -> None:
    policy = TerminationPolicy(max_review_iterations=10, max_cost_usd=0.5, max_workers=6)
    cost_reason = decide_termination(
        policy, completed_iterations=1, cost_used=0.5, worker_count=1, no_progress=False
    )
    assert cost_reason is not None and "cost budget" in cost_reason
    worker_reason = decide_termination(
        policy, completed_iterations=1, cost_used=0.1, worker_count=6, no_progress=False
    )
    assert worker_reason is not None and "worker budget" in worker_reason


def test_termination_stops_on_no_progress() -> None:
    reason = decide_termination(
        TerminationPolicy(max_review_iterations=10),
        completed_iterations=1,
        cost_used=0.0,
        worker_count=0,
        no_progress=True,
    )
    assert reason is not None and "no progress" in reason


def test_termination_reports_the_first_exhausted_limit_deterministically() -> None:
    # Iterations are checked before cost, workers, and no-progress.
    reason = decide_termination(
        TerminationPolicy(max_review_iterations=1, max_cost_usd=0.1, max_workers=1),
        completed_iterations=1,
        cost_used=1.0,
        worker_count=5,
        no_progress=True,
    )
    assert reason is not None and "maximum review iterations" in reason
