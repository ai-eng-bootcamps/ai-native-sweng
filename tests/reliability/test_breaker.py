"""Circuit breaker: consecutive failures per boundary (Lesson 7.5).

These fail against the scaffolding stubs and pass once Module 7 is implemented.
"""

import pytest

from anse_harness.reliability import CircuitBreaker

pytestmark = pytest.mark.student_impl


def test_breaker_stays_closed_below_the_threshold() -> None:
    breaker = CircuitBreaker(threshold=3)
    breaker.record_failure("model")
    breaker.record_failure("model")
    assert breaker.count("model") == 2
    assert breaker.is_open("model") is False


def test_breaker_opens_at_the_threshold() -> None:
    breaker = CircuitBreaker(threshold=3)
    for _ in range(3):
        breaker.record_failure("model")
    assert breaker.is_open("model") is True


def test_success_closes_the_circuit_again() -> None:
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure("model")
    breaker.record_failure("model")
    assert breaker.is_open("model") is True
    breaker.record_success("model")
    assert breaker.count("model") == 0
    assert breaker.is_open("model") is False


def test_boundaries_are_counted_independently() -> None:
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure("model")
    breaker.record_failure("tool")
    assert breaker.is_open("model") is False
    assert breaker.is_open("tool") is False
    breaker.record_failure("tool")
    assert breaker.is_open("tool") is True
    assert breaker.is_open("model") is False
