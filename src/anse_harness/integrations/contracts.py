"""Typed integration contracts and the transport seam (Lesson 9.1; arch-ref 37, 60, 63).

An integration boundary is where the harness reaches a system outside its process
and repository. Lesson 9.1 asks for a *typed* boundary: a request whose method,
path, and body are shaped by the adapter (never by the model), a typed response,
error semantics that map onto the Module 7 failure taxonomy (retryable versus
permanent), lifecycle control (timeout, cancellation), and an audit record of
every outward action.

The single most important shape here is the **Transport seam**. The adapter does
all the logic - request shaping, the hard-coded ``draft`` flag, the idempotency
marker, approval routing, audit tracing - and hands a fully shaped
``IntegrationRequest`` to an injected ``Transport``. Offline that transport is the
deterministic in-process double (``local_double.LocalGitHubDouble``); live it is
the ``urllib`` sender in ``github.LiveHTTPTransport``. Only the transport differs
between the two, and the live one is the only code that ever opens a socket.

Credentials never travel through these contracts. A token lives in the process
environment and, on a live send, only on the wire (an ``Authorization`` header);
it is never placed in a request body, an audit record, or a trace payload
(arch-ref 63). ``TraceEvent.sensitive_keys`` redaction is the belt-and-braces
backstop, not the primary defence.

SCAFFOLDING: everything in this module is supplied. The student-implemented
surfaces are the adapter methods (``github``) and the MCP client
(``mcp_client``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from anse_harness.tracing import TraceEvent, TraceWriter

#: The complete outward surface of the repository-platform boundary (arch-ref 60,
#: canonical §6 class 3). There is deliberately no ``merge``, ``push``,
#: ``create_release``, or ``deploy`` action: prohibited actions (class 4/5) are
#: absent from the surface, not merely denied.
INTEGRATION_ACTIONS = ("read_issue", "read_ci_status", "create_draft_pr")

#: How an external action ended, for the audit record (arch-ref 60, spec §16).
AUDIT_OUTCOMES = ("completed", "deduplicated", "rejected", "cancelled", "failed")


@dataclass(frozen=True)
class IntegrationRequest:
    """A typed, transport-agnostic external-action request (Lesson 9.1).

    The adapter shapes ``method``, ``path``, and ``body``; the model never does.
    ``idempotency_key`` is set for repeatable consequential actions (arch-ref 53)
    so a duplicate request can be detected instead of re-executed.
    """

    action: str
    method: str
    path: str
    body: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize for audit and trace payloads. Never carries a credential."""
        return {
            "action": self.action,
            "method": self.method,
            "path": self.path,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class IntegrationResponse:
    """A typed external-action response."""

    action: str
    status: int
    data: dict[str, Any]


class IntegrationError(Exception):
    """An external-action failure.

    ``retryable`` maps onto the Module 7 failure taxonomy: a timeout or a 5xx is
    retryable; a 404, a validation refusal, or a forced non-draft create is not.
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class IntegrationCancelledError(Exception):
    """Raised when a request is cancelled before it reaches the transport."""


class Transport(Protocol):
    """The offline/live split point: send one shaped request, return one response."""

    def send(self, request: IntegrationRequest) -> IntegrationResponse: ...


@dataclass(frozen=True)
class ExternalActionAudit:
    """External-action audit record (spec §16 new artifact; arch-ref 60, 63).

    A durable record that an outward action was requested, whether it was
    approved, and how it ended - the evidence a reviewer reads after the fact.
    Credentials never appear in an audit record.
    """

    action: str
    method: str
    path: str
    idempotency_key: str | None
    approved: bool
    outcome: str
    status: int | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.outcome not in AUDIT_OUTCOMES:
            raise ValueError(f"unknown audit outcome: {self.outcome!r}")

    def to_payload(self) -> dict[str, Any]:
        """Serialize as an ``artifact_created`` trace payload."""
        return {
            "artifact_type": "external_action_audit",
            "artifact_id": audit_artifact_id(self.action, self.idempotency_key),
            "action": self.action,
            "method": self.method,
            "path": self.path,
            "idempotency_key": self.idempotency_key,
            "approved": self.approved,
            "outcome": self.outcome,
            "status": self.status,
            "detail": self.detail,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> ExternalActionAudit:
        """Rebuild an audit record from its trace payload."""
        return cls(
            action=str(data["action"]),
            method=str(data["method"]),
            path=str(data["path"]),
            idempotency_key=data["idempotency_key"],
            approved=bool(data["approved"]),
            outcome=str(data["outcome"]),
            status=None if data.get("status") is None else int(data["status"]),
            detail=str(data.get("detail", "")),
        )


def audit_artifact_id(action: str, idempotency_key: str | None) -> str:
    """Deterministic id for one external-action audit record."""
    suffix = idempotency_key if idempotency_key else "read"
    return f"audit-{action}-{suffix}"


#: The integration options a protocol-decision record chooses between (Lesson 9.6).
PROTOCOL_OPTIONS = (
    "direct_function_call",
    "local_process",
    "rest_api",
    "mcp",
    "agent_to_agent",
)

#: Local options that need no protocol justification (arch-ref 61: ordinary typed
#: interfaces for in-process, shared-ownership, no-interoperability components).
LOCAL_PROTOCOL_OPTIONS = ("direct_function_call", "local_process")

#: The reasons that justify a protocol boundary (arch-ref 61; Evidence Gate 5).
PROTOCOL_JUSTIFICATIONS = (
    "process_isolation",
    "independent_deployment",
    "external_ownership",
    "technology_boundary",
    "ecosystem_interoperability",
    "reusable_capability_discovery",
)


@dataclass(frozen=True)
class ProtocolDecisionRecord:
    """Protocol-decision record (spec §16 new artifact; Lesson 9.6, Evidence Gate 5).

    Records which integration option was chosen for one capability and why an
    ordinary local interface is insufficient. ``validate`` supplies the narrow,
    deterministic part of the Evidence Gate 5 check (the chosen option is one of
    the five; a non-local choice names at least one arch-ref-61 justification, and
    every justification is drawn from the closed vocabulary); the rest of the gate
    is a human rubric.
    """

    capability: str
    chosen: str
    justifications: tuple[str, ...]
    rejected_alternatives: tuple[str, ...]
    rationale: str

    def validate(self) -> None:
        """Raise ``ValueError`` if the record fails the deterministic gate checks."""
        if self.chosen not in PROTOCOL_OPTIONS:
            raise ValueError(f"unknown protocol option: {self.chosen!r}")
        for alternative in self.rejected_alternatives:
            if alternative not in PROTOCOL_OPTIONS:
                raise ValueError(f"unknown rejected alternative: {alternative!r}")
        for justification in self.justifications:
            if justification not in PROTOCOL_JUSTIFICATIONS:
                raise ValueError(f"unknown protocol justification: {justification!r}")
        if self.chosen not in LOCAL_PROTOCOL_OPTIONS and not self.justifications:
            raise ValueError(
                f"choosing {self.chosen!r} over a local interface requires at least one "
                "arch-ref-61 justification"
            )
        if not self.rationale.strip():
            raise ValueError("a protocol-decision record must carry a rationale")

    def to_payload(self) -> dict[str, Any]:
        """Serialize the record (for an ``artifact_created`` payload or a file)."""
        return {
            "artifact_type": "protocol_decision_record",
            "capability": self.capability,
            "chosen": self.chosen,
            "justifications": list(self.justifications),
            "rejected_alternatives": list(self.rejected_alternatives),
            "rationale": self.rationale,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> ProtocolDecisionRecord:
        """Rebuild a record from its payload and validate it."""
        record = cls(
            capability=str(data["capability"]),
            chosen=str(data["chosen"]),
            justifications=tuple(data.get("justifications", ())),
            rejected_alternatives=tuple(data.get("rejected_alternatives", ())),
            rationale=str(data.get("rationale", "")),
        )
        record.validate()
        return record


class IntegrationRecorder:
    """Assigns sequential namespaced event ids and writes trace events, or no-ops.

    Integration events reuse the existing ``tool_*`` vocabulary (external actions
    are tool calls at a remote boundary; the frozen event set is not extended).
    Sequential ids (``evt-int-0000`` ...) make a recorded integration trace
    replay byte-for-byte against the deterministic double.
    """

    def __init__(
        self,
        writer: TraceWriter | None,
        run_id: str,
        workflow_id: str,
        prefix: str = "evt-int",
    ) -> None:
        self._writer = writer
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._prefix = prefix
        self._seq = 0

    def emit(
        self,
        event_type: str,
        component: str,
        payload: dict[str, Any],
        *,
        status: str = "ok",
        parent_event_id: str | None = None,
        sensitive_keys: tuple[str, ...] = (),
    ) -> str:
        event_id = f"{self._prefix}-{self._seq:04d}"
        self._seq += 1
        if self._writer is not None:
            self._writer.write(
                TraceEvent(
                    run_id=self._run_id,
                    workflow_id=self._workflow_id,
                    component=component,
                    event_type=event_type,
                    status=status,
                    payload=payload,
                    event_id=event_id,
                    parent_event_id=parent_event_id,
                    sensitive_keys=sensitive_keys,
                )
            )
        return event_id
