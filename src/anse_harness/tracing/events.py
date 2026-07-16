"""Trace event schema and event-category vocabulary (spec 19).

Every major component emits structured trace events. TraceEvent carries the
required fields: timestamp, run ID, workflow ID, component, event type, status,
optional parent event, a structured payload, and a sensitive-data
classification. Payload keys listed in sensitive_keys are redacted by the
trace writer before anything reaches disk (spec 19: sensitive content should
not be logged indiscriminately). Full format documentation: docs/trace-events.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Required event categories (spec 19).
EVENT_TYPES = frozenset(
    {
        "run_started",
        "run_completed",
        "run_failed",
        "model_requested",
        "model_responded",
        "model_failed",
        "context_packet_created",
        "tool_requested",
        "policy_evaluated",
        "approval_requested",
        "approval_resolved",
        "tool_completed",
        "tool_failed",
        "state_transitioned",
        "worker_started",
        "worker_completed",
        "worker_failed",
        "validation_started",
        "validation_completed",
        "checkpoint_created",
        "retry_scheduled",
        "escalation_created",
        "budget_updated",
        "budget_exhausted",
        "artifact_created",
    }
)

#: Sensitive-data classification values.
SENSITIVITY_LEVELS = ("public", "sensitive")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class TraceEvent:
    """One structured trace event (spec 19)."""

    run_id: str
    workflow_id: str
    component: str
    event_type: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_event_id: str | None = None
    #: Sensitive-data classification for the event as a whole.
    sensitivity: str = "public"
    #: Payload keys (matched at any nesting depth) whose values must be redacted.
    sensitive_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown trace event type: {self.event_type!r}")
        if self.sensitivity not in SENSITIVITY_LEVELS:
            raise ValueError(f"unknown sensitivity level: {self.sensitivity!r}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the JSON object written as one JSONL line."""
        return {
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "component": self.component,
            "event_type": self.event_type,
            "status": self.status,
            "parent_event_id": self.parent_event_id,
            "payload": self.payload,
            "sensitivity": self.sensitivity,
            "sensitive_keys": list(self.sensitive_keys),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraceEvent:
        """Deserialize one JSONL line back into a TraceEvent."""
        return cls(
            run_id=str(data["run_id"]),
            workflow_id=str(data["workflow_id"]),
            component=str(data["component"]),
            event_type=str(data["event_type"]),
            status=str(data["status"]),
            payload=dict(data.get("payload", {})),
            timestamp=str(data["timestamp"]),
            event_id=str(data["event_id"]),
            parent_event_id=data.get("parent_event_id"),
            sensitivity=str(data.get("sensitivity", "public")),
            sensitive_keys=tuple(data.get("sensitive_keys", ())),
        )
