"""Approval gate: explicit human decisions at the approval boundary (spec 7.14; Lesson 3.5).

Nothing consequential leaves the sandbox on the agent's own authority. An
``ApprovalRequest`` names the action, the reason, the affected assets, the risk
classification, the proposed diff, and the validation status - the evidence a human
decides on. The gate itself is deliberately small: it forwards each request to a
``resolver`` (an interactive prompt in the CLI, a fixed decision in tests) and records
every request/decision pair so the run's trace can show what was asked and what was
answered.

The default resolver rejects everything: an approval boundary that approves by default
is not a boundary. Core labs resolve approvals through the CLI; a user interface is
optional (spec 7.14).

SCAFFOLDING: the request/decision contracts and the resolvers are supplied; implement
``ApprovalGate.request`` in Module 3, Lesson 3.5.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ApprovalDecision(StrEnum):
    """Approval outcomes (spec 7.14). Core labs use approved and rejected."""

    APPROVED = "approved"
    REJECTED = "rejected"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    EXPIRED = "expired"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class ApprovalRequest:
    """One request for a human decision (spec 7.14: the evidence an approver acts on)."""

    #: The action awaiting approval, e.g. "delete_file" or "finalize_patch".
    action: str
    #: Why the agent or harness is asking.
    reason: str
    #: Repository-relative paths the action affects.
    affected_paths: tuple[str, ...] = ()
    #: Risk classification (capability/side-effect class vocabulary).
    risk: str = ""
    #: The proposed change, when one exists (a unified diff).
    diff: str | None = None
    #: Validation status at request time: True/False once validation ran, None before.
    validation_ok: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize for trace payloads (approval_requested)."""
        return {
            "action": self.action,
            "reason": self.reason,
            "affected_paths": list(self.affected_paths),
            "risk": self.risk,
            "diff": self.diff,
            "validation_ok": self.validation_ok,
        }


def reject_all(request: ApprovalRequest) -> ApprovalDecision:
    """The default resolver: reject every request (deny by default)."""
    return ApprovalDecision.REJECTED


def approve_all(request: ApprovalRequest) -> ApprovalDecision:
    """Approve every request. For tests and recorded demonstrations only."""
    return ApprovalDecision.APPROVED


class ApprovalGate:
    """Routes approval requests to a resolver and records every decision."""

    def __init__(
        self, resolver: Callable[[ApprovalRequest], ApprovalDecision] = reject_all
    ) -> None:
        self._resolver = resolver
        #: Every (request, decision) pair, in order. The write runtime reads this to
        #: record approvals in the trace.
        self.log: list[tuple[ApprovalRequest, ApprovalDecision]] = []

    def request(self, request: ApprovalRequest) -> ApprovalDecision:
        """Resolve one approval request and record the outcome."""
        raise NotImplementedError(
            "Module 3, Lesson 3.5: pass the request to the resolver, append the "
            "(request, decision) pair to self.log, and return the decision."
        )
