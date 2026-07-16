"""Model adapter errors, including provider error normalization (spec 7.1).

Live adapters translate provider-specific exceptions into ProviderError so the
rest of the harness never handles SDK exception types directly. The retryable
flag implements the retryable-error classification responsibility.
"""

from __future__ import annotations

#: HTTP status codes that are safe to retry (matches SDK retry defaults).
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})


def classify_retryable_status(status_code: int) -> bool:
    """Classify an HTTP status code as retryable (429, 408, 409, and 5xx)."""
    return status_code in RETRYABLE_STATUS_CODES or status_code >= 500


class ModelAdapterError(Exception):
    """Base class for all model adapter errors."""


class ConfigError(ModelAdapterError):
    """The model configuration is missing, malformed, or inconsistent."""


class MissingProviderSDKError(ModelAdapterError):
    """A live provider adapter was requested but its SDK is not installed."""

    def __init__(self, provider: str, package: str) -> None:
        super().__init__(
            f"The '{provider}' provider requires the '{package}' package, which is not "
            f"installed. Install the optional live dependencies with: uv sync --extra live"
        )
        self.provider = provider
        self.package = package


class ProviderError(ModelAdapterError):
    """A normalized provider failure, carrying the retryable classification."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code


class ModelTimeoutError(ProviderError):
    """The provider did not respond within the request timeout (always retryable)."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class ScriptError(ModelAdapterError):
    """Base class for scripted-mode errors."""


class ScriptExhaustedError(ScriptError):
    """The scripted adapter received more requests than the script contains."""


class ScriptMismatchError(ScriptError):
    """A request did not match the expectation recorded for the next script step."""


class ReplayError(ModelAdapterError):
    """Base class for replay-mode errors."""


class ReplayExhaustedError(ReplayError):
    """The replay adapter received more requests than the trace contains."""


class ReplayMismatchError(ReplayError):
    """A request did not match the recorded request at this point in the trace."""
