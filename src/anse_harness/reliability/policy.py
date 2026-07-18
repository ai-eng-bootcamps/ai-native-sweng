"""Retry policy: declarative table, explicit decisions, no blind retries (Lesson 7.2).

Retries must be intentional (arch-ref 51): the retry MODE is matched to the failure
class, the attempt budget is explicit, and some failures are never retried at all -
most importantly, a policy denial is not retried without a changed approval or
policy state. The policy is DATA (``DEFAULT_RETRY_POLICY``), the decision is a pure
function (``decide_retry``), and every decision becomes a persisted artifact
(``RetryDecision``) so the retry history of a run is readable from its store.

The decision record carries ``observed_attempt_cost_usd``: the model spend of the
FAILED attempt, read from its trace. A crashed attempt's cost never reaches the
workflow state's budgets (the loops fold cost into state only at stage end), so
this field is where that spend stays visible - see Lesson 7.2's honesty note.

``detect_no_progress_window`` (Lesson 7.5) generalizes Module 6's consecutive-repeat
detector to a HISTORY WINDOW, catching the oscillation pattern of arch-ref 49
(fix A -> fix B -> fix A ...) that consecutive comparison cannot see.

SCAFFOLDING: the table, the modes, and the record contract are supplied; implement
``decide_retry`` and ``detect_no_progress_window`` in Module 7, Lessons 7.2 and 7.5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from anse_harness.budgets.policy import LoopSnapshot
from anse_harness.reliability.classify import FailureClassification


class RetryMode(StrEnum):
    """The intentional retry modes of architecture-reference section 51."""

    SAME_INPUT = "same-input retry"
    REVISED_CONTEXT = "revised-context retry"
    REPLAN = "replanning"
    FALLBACK_MODEL = "alternative model"
    ESCALATE = "human escalation"


@dataclass(frozen=True)
class RetryRule:
    """One row of the retry table: how a failure class may be retried, and how often.

    ``max_attempts`` counts TOTAL attempts including the first; 0 means the class
    is never retried (its mode is the response, applied by a human).
    """

    mode: RetryMode
    max_attempts: int


#: The default retry table: canonical failure class -> retry rule (arch-ref 51).
#: Transient faults retry on the same input; malformed output suggests a more
#: capable model; context/tool/validation failures need revised context; planning
#: and implementation failures need replanning; everything that requires human
#: judgment - policy denial above all - escalates and is never blindly retried.
DEFAULT_RETRY_POLICY: dict[str, RetryRule] = {
    "transient infrastructure failure": RetryRule(RetryMode.SAME_INPUT, 3),
    "model-provider failure": RetryRule(RetryMode.SAME_INPUT, 3),
    "malformed output": RetryRule(RetryMode.FALLBACK_MODEL, 2),
    "tool failure": RetryRule(RetryMode.REVISED_CONTEXT, 2),
    "context failure": RetryRule(RetryMode.REVISED_CONTEXT, 2),
    "planning failure": RetryRule(RetryMode.REPLAN, 2),
    "implementation failure": RetryRule(RetryMode.REPLAN, 2),
    "validation failure": RetryRule(RetryMode.REVISED_CONTEXT, 2),
    "policy denial": RetryRule(RetryMode.ESCALATE, 0),
    "review failure": RetryRule(RetryMode.ESCALATE, 0),
    "integration conflict": RetryRule(RetryMode.ESCALATE, 0),
    "budget exhaustion": RetryRule(RetryMode.ESCALATE, 0),
    "approval timeout": RetryRule(RetryMode.ESCALATE, 0),
    "insufficient evidence": RetryRule(RetryMode.ESCALATE, 0),
    "persistent unknown failure": RetryRule(RetryMode.ESCALATE, 0),
}


@dataclass(frozen=True)
class RetryDecision:
    """One explicit retry decision, persisted as the retry-decision artifact."""

    #: "retry" or "escalate".
    action: str
    mode: RetryMode
    failure_class: str
    boundary: str
    #: The attempt number that just failed (1-based).
    failed_attempt: int
    #: The attempt a retry would run; None when the action is escalate.
    next_attempt: int | None
    reason: str
    #: Model spend of the failed attempt, read from its trace; None when unknown.
    #: This spend is NOT in the workflow state's budgets (see module docstring).
    observed_attempt_cost_usd: float | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the retry-decision artifact."""
        return {
            "artifact_type": "retry_decision",
            "action": self.action,
            "mode": self.mode.value,
            "failure_class": self.failure_class,
            "boundary": self.boundary,
            "failed_attempt": self.failed_attempt,
            "next_attempt": self.next_attempt,
            "reason": self.reason,
            "observed_attempt_cost_usd": self.observed_attempt_cost_usd,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> RetryDecision:
        """Deserialize one artifact payload back into a RetryDecision."""
        next_attempt = data.get("next_attempt")
        cost = data.get("observed_attempt_cost_usd")
        return cls(
            action=str(data["action"]),
            mode=RetryMode(str(data["mode"])),
            failure_class=str(data["failure_class"]),
            boundary=str(data["boundary"]),
            failed_attempt=int(data["failed_attempt"]),
            next_attempt=None if next_attempt is None else int(next_attempt),
            reason=str(data["reason"]),
            observed_attempt_cost_usd=None if cost is None else float(cost),
        )


def retry_artifact_id(task_id: str, index: int) -> str:
    """Deterministic identifier of the nth retry-decision artifact."""
    return f"retry-decision-{task_id}-{index}"


def decide_retry(
    policy: Mapping[str, RetryRule],
    classification: FailureClassification,
    *,
    attempt: int,
    approval_state_changed: bool = False,
) -> RetryDecision:
    """Decide the response to one classified failure (arch-ref 51), deterministically.

    ``attempt`` is the attempt number that just failed (1-based). The checks run
    in this fixed order, and the first that applies decides:

    1. No rule for the class -> escalate, reason
       ``"failure class <class> has no retry rule; human escalation"``.
    2. Policy denial is special-cased: with ``approval_state_changed`` True the
       retry is permitted (mode same-input retry, next attempt), reason
       ``"approval state changed; retry permitted"``; otherwise escalate, reason
       ``"policy denial is never retried without a changed approval or policy state"``.
    3. Rule mode is human escalation, or ``max_attempts`` is 0 -> escalate,
       reason ``"<class> escalates by policy"``.
    4. The classification is not same-input retryable and the rule mode is
       same-input retry -> escalate, reason
       ``"non-retryable failure: a same-input retry would reproduce it"``.
    5. ``attempt >= max_attempts`` -> escalate, reason
       ``"retry budget exhausted: <attempt> of <max_attempts> attempts used"``.
    6. Otherwise retry with the rule's mode and ``next_attempt = attempt + 1``,
       reason ``"<mode> permitted: attempt <attempt + 1> of <max_attempts>"``.

    Every decision carries the classification's class and boundary;
    ``observed_attempt_cost_usd`` stays None here (the controller fills it in).
    """
    raise NotImplementedError(
        "Module 7, Lesson 7.2: apply the six documented checks in order and return "
        "the RetryDecision with the pinned reason strings."
    )


def detect_no_progress_window(history: Sequence[LoopSnapshot], *, window: int = 4) -> str | None:
    """Detect repeated OR oscillating loop states over a history window (arch-ref 49).

    ``history`` holds one ``LoopSnapshot`` per completed iteration, oldest first.
    The latest snapshot is compared against each of the up to ``window`` snapshots
    immediately before it, most recent first; the first equal snapshot decides
    (snapshots are frozen dataclasses - equality compares patch fingerprint and
    finding keys). With fewer than two snapshots there is never no-progress.

    The returned reason pins the pattern, with 1-based iteration numbers:

    * the immediately preceding snapshot matched ->
      ``"no progress: iteration <n> repeated iteration <n - 1> (identical patch
      and findings)"`` - Module 6's consecutive-repeat rule;
    * an earlier snapshot within the window matched ->
      ``"no progress: iteration <n> repeated iteration <j> (oscillating fixes)"``
      - the alternating-fix pattern consecutive comparison cannot see.

    Returns None when no snapshot in the window matches.
    """
    raise NotImplementedError(
        "Module 7, Lesson 7.5: with n = len(history), compare history[n - 1] "
        "against history[j - 1] for j from n - 1 down to max(1, n - window); on "
        "the first match return the pinned reason (adjacent match -> 'identical "
        "patch and findings', earlier match -> 'oscillating fixes'); else None."
    )
