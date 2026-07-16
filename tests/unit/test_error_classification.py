"""Unit tests for retryable-error classification and error normalization (spec 7.1)."""

from anse_harness.models import ModelTimeoutError, ProviderError, classify_retryable_status


def test_retryable_status_codes() -> None:
    assert classify_retryable_status(408)
    assert classify_retryable_status(409)
    assert classify_retryable_status(429)
    assert classify_retryable_status(500)
    assert classify_retryable_status(529)


def test_non_retryable_status_codes() -> None:
    assert not classify_retryable_status(400)
    assert not classify_retryable_status(401)
    assert not classify_retryable_status(403)
    assert not classify_retryable_status(404)


def test_provider_error_carries_classification() -> None:
    err = ProviderError("rate limited", provider="anthropic", retryable=True, status_code=429)
    assert err.retryable
    assert err.provider == "anthropic"
    assert err.status_code == 429


def test_timeout_is_always_retryable() -> None:
    err = ModelTimeoutError("timed out", provider="openai")
    assert err.retryable
    assert isinstance(err, ProviderError)
