"""Circuit breaker: stop retrying a boundary that keeps failing (Lesson 7.5).

A retry policy judges one failure at a time; the circuit breaker judges the
PATTERN. When the same boundary (model, tool, sandbox, state store, ...) fails
repeatedly in a row, another same-input retry is spending budget on a fault that
is evidently not transient - the breaker OPENS and the reliability controller
short-circuits to human escalation instead of scheduling another attempt
(spec section 16, Module 7: circuit breaker).

The breaker is deliberately minimal state: one consecutive-failure counter per
boundary. A success on a boundary closes its circuit again (the counter resets);
failures on one boundary never open another boundary's circuit. It lives in the
reliability controller, NOT in the engine loops - reliability drives the workflow
from outside.

SCAFFOLDING: the class shape is supplied; implement ``record_failure``,
``record_success``, and ``is_open`` in Module 7, Lesson 7.5.
"""

from __future__ import annotations


class CircuitBreaker:
    """Consecutive-failure circuit breaker, counted per boundary."""

    def __init__(self, threshold: int = 3) -> None:
        if threshold < 1:
            raise ValueError("circuit breaker threshold must be at least 1")
        #: Consecutive failures at which a boundary's circuit opens.
        self.threshold = threshold
        self._consecutive: dict[str, int] = {}

    def count(self, boundary: str) -> int:
        """The current consecutive-failure count for one boundary."""
        return self._consecutive.get(boundary, 0)

    def record_failure(self, boundary: str) -> None:
        """Count one more consecutive failure at this boundary."""
        raise NotImplementedError(
            "Module 7, Lesson 7.5: increment this boundary's consecutive-failure count by one."
        )

    def record_success(self, boundary: str) -> None:
        """A success at this boundary closes its circuit: the count resets to zero."""
        raise NotImplementedError(
            "Module 7, Lesson 7.5: reset this boundary's consecutive-failure count to zero."
        )

    def is_open(self, boundary: str) -> bool:
        """True when this boundary has reached the threshold: do not retry, escalate."""
        raise NotImplementedError(
            "Module 7, Lesson 7.5: return whether this boundary's consecutive-"
            "failure count has reached the threshold."
        )
