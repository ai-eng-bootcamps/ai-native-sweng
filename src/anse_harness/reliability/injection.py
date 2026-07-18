"""Failure injection: break the workflow deliberately, deterministically (Lesson 7.6).

Module 7's injections split into three channels, by WHERE the failure lives:

* **Script channel** - content failures (malformed structured output, a tool call
  with contract-violating arguments, an edit that fails validation, a repeated
  review finding) are expressed IN the scripted conversation. They record like any
  run and replay for free: the recorded trace already contains the failure.
* **Raise channel** - provider failures are EXCEPTIONS, not content; they never
  appear as trace interactions. They are injected declaratively: an
  ``InjectionSpec`` drives the ``FailureInjectionAdapter``, which counts its OWN
  ``complete()`` calls and raises BEFORE consulting the inner adapter - so the
  same spec wraps a ``ScriptedAdapter`` when recording and a ``ReplayAdapter``
  when replaying, and the failure fires at the identical call in both modes
  without desynchronizing the replay position. A raise-injected trace therefore
  REQUIRES its spec at replay: without it, replay fails loudly (the trace holds
  one more request than it holds responses). That is by design - the spec is
  replay configuration and ships next to the trace, never decoration.
* **Store channel** - checkpoint corruption touches no model interaction at all:
  ``corrupt_latest_snapshot`` tampers with the persisted snapshot on disk, and
  the store's schema versioning must refuse it loudly on resume.

SCAFFOLDING: the spec schema, the error factory, and the store corrupter are
supplied; implement ``FailureInjectionAdapter.complete`` in Module 7, Lesson 7.6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anse_harness.models import ModelAdapter
from anse_harness.models.errors import ModelTimeoutError, ProviderError
from anse_harness.models.types import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    Usage,
)

#: The injectable raise-level failure kinds.
INJECTION_FAILURE_KINDS: tuple[str, ...] = (
    "model_timeout",
    "provider_error_retryable",
    "provider_error_permanent",
)


@dataclass(frozen=True)
class InjectionSpec:
    """One declarative raise-level injection: fail the nth call at a boundary.

    ``at_call`` is 1-based and counts the WRAPPER's ``complete()`` calls, so an
    injected raise never consumes the inner adapter's script or replay position.
    The spec is JSON-able: a committed raise-injected trace ships its spec beside
    it, and replaying that trace without the spec fails loudly by design.
    """

    at_call: int
    failure: str
    boundary: str = "model"

    def __post_init__(self) -> None:
        if self.at_call < 1:
            raise ValueError("at_call is 1-based and must be at least 1")
        if self.failure not in INJECTION_FAILURE_KINDS:
            raise ValueError(
                f"unknown injection failure {self.failure!r}; "
                f"expected one of {', '.join(INJECTION_FAILURE_KINDS)}"
            )
        if self.boundary != "model":
            raise ValueError("raise-level injection supports only the model boundary")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the committed injection-spec asset."""
        return {"boundary": self.boundary, "at_call": self.at_call, "failure": self.failure}

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> InjectionSpec:
        """Deserialize one payload back into an InjectionSpec."""
        return cls(
            at_call=int(data["at_call"]),
            failure=str(data["failure"]),
            boundary=str(data.get("boundary", "model")),
        )

    @classmethod
    def from_file(cls, path: Path) -> InjectionSpec:
        """Load a committed injection spec (``*.injection.json``)."""
        with path.open(encoding="utf-8") as f:
            return cls.from_payload(json.load(f))

    def save(self, path: Path) -> None:
        """Write the spec as the committed asset format (stable serialization)."""
        path.write_text(
            json.dumps(self.to_payload(), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )


def injection_error(kind: str) -> ProviderError:
    """Build the provider error one injection kind stands for."""
    if kind == "model_timeout":
        return ModelTimeoutError("injected: request timed out", provider="injected")
    if kind == "provider_error_retryable":
        return ProviderError(
            "injected: internal server error",
            provider="injected",
            retryable=True,
            status_code=500,
        )
    if kind == "provider_error_permanent":
        return ProviderError(
            "injected: invalid request",
            provider="injected",
            retryable=False,
            status_code=400,
        )
    raise ValueError(f"unknown injection failure {kind!r}")


class FailureInjectionAdapter(ModelAdapter):
    """Wraps any model adapter and raises the configured failure at the configured call.

    With ``spec=None`` the wrapper is transparent - the injection harness can wrap
    unconditionally and turn failures on per run. The wrapper counts its own
    completed ``complete()`` calls in ``calls``.
    """

    def __init__(self, inner: ModelAdapter, spec: InjectionSpec | None) -> None:
        super().__init__(None)
        self._inner = inner
        self._spec = spec
        #: How many complete() calls this wrapper has seen (including the injected one).
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Delegate to the inner adapter, or raise the injected failure at its call.

        Count this call first; when a spec is configured and its ``at_call``
        equals the count, raise ``injection_error(spec.failure)`` BEFORE touching
        the inner adapter - the inner script/replay position must not advance on
        an injected raise, or record and replay would desynchronize.
        """
        raise NotImplementedError(
            "Module 7, Lesson 7.6: increment self.calls; if the spec matches the "
            "count, raise injection_error(self._spec.failure) without consulting "
            "the inner adapter; otherwise return self._inner.complete(request)."
        )

    def capabilities(self) -> ModelCapabilities:
        """Capability metadata passes through unchanged."""
        return self._inner.capabilities()

    def calculate_cost(self, usage: Usage) -> float:
        """Cost calculation passes through unchanged."""
        return self._inner.calculate_cost(usage)


def corrupt_latest_snapshot(
    store_root: Path, workflow_id: str, *, schema_version: str = "corrupted"
) -> Path:
    """Tamper with the latest persisted snapshot's schema version, on disk.

    The store-channel injection for the checkpoint-interruption failure class: a
    resumed workflow must detect the tampering loudly (``StateSchemaError``), never
    silently restart. Rewrites the snapshot with the store's own stable
    serialization and returns its path.
    """
    snapshots = sorted((store_root / workflow_id / "snapshots").glob("state-v*.json"))
    if not snapshots:
        raise FileNotFoundError(f"no snapshots persisted for workflow {workflow_id!r}")
    latest = snapshots[-1]
    document = json.loads(latest.read_text(encoding="utf-8"))
    document["state"]["schema_version"] = schema_version
    latest.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return latest
