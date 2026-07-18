"""Window-based no-progress detection: repeats AND oscillation (Lesson 7.5).

Module 6's detector compares consecutive iterations only; the Module 7
generalization looks back over a window, so the alternating-fix pattern of
arch-ref 49 (fix A -> fix B -> fix A) is also caught. These fail against the
scaffolding stubs and pass once Module 7 is implemented.
"""

import pytest

from anse_harness.budgets.policy import LoopSnapshot
from anse_harness.reliability import detect_no_progress_window

pytestmark = pytest.mark.student_impl


def _snap(patch: str, *keys: str) -> LoopSnapshot:
    return LoopSnapshot(patch_fingerprint=patch, finding_keys=tuple(keys))


def test_fewer_than_two_iterations_is_never_no_progress() -> None:
    assert detect_no_progress_window([]) is None
    assert detect_no_progress_window([_snap("a", "k1")]) is None


def test_consecutive_repeat_is_detected_with_module6_semantics() -> None:
    history = [_snap("a", "k1"), _snap("a", "k1")]
    assert detect_no_progress_window(history) == (
        "no progress: iteration 2 repeated iteration 1 (identical patch and findings)"
    )


def test_progress_in_either_fingerprint_is_progress() -> None:
    # Patch changed, findings repeated: something moved.
    assert detect_no_progress_window([_snap("a", "k1"), _snap("b", "k1")]) is None
    # Findings changed, patch identical: the review surfaced something new.
    assert detect_no_progress_window([_snap("a", "k1"), _snap("a", "k2")]) is None


def test_oscillating_fixes_are_detected_across_the_window() -> None:
    # A -> B -> A: consecutive comparison sees progress every step; the window
    # sees iteration 3 reproducing iteration 1.
    history = [_snap("a", "k1"), _snap("b", "k1"), _snap("a", "k1")]
    assert detect_no_progress_window(history) == (
        "no progress: iteration 3 repeated iteration 1 (oscillating fixes)"
    )


def test_repeats_beyond_the_window_are_not_reported() -> None:
    # The matching snapshot is 4 iterations back; a window of 3 cannot see it.
    history = [
        _snap("a", "k1"),
        _snap("b", "k1"),
        _snap("c", "k1"),
        _snap("d", "k1"),
        _snap("a", "k1"),
    ]
    assert detect_no_progress_window(history, window=3) is None
    assert detect_no_progress_window(history, window=4) == (
        "no progress: iteration 5 repeated iteration 1 (oscillating fixes)"
    )
