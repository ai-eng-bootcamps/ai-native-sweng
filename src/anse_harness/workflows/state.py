"""Workflow state schema (canonical-reference.md section 13).

Workflow state is the explicit, versioned record of everything a stateful workflow
knows about itself: the task it serves, its current stage and status, the artifacts it
has produced, the workers it has invoked, the budgets it has consumed, the approvals
it has resolved, the failures it has recorded, and its latest checkpoint. Every group
below mirrors the canonical schema exactly. The workflow engine mutates ONE state
object as stages run; the state store persists versioned snapshots of it at stage
boundaries (Module 5, Lessons 5.2 and 5.5).

The canonical status vocabulary is pending / running / awaiting_approval / completed /
failed / escalated; ``cancelled`` is added for the explicit cancellation terminal that
the architecture reference's transition rules (section 19) and the Module 5 required
validations demand - a cancelled workflow must not masquerade as failed.

State formats are versioned (spec 7.10): every serialized state carries
``schema_version``, and deserializing a snapshot written under a different schema
version fails loudly with ``StateSchemaError`` - a store must never quietly
reinterpret old state.

SUPPLIED infrastructure: the schema and its serialization are consumed as-is; the
store that persists it (``state/store.py``) and the engine that drives it
(``workflows/engine.py``) are yours to implement in Module 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: Version stamp written into every serialized workflow state (spec 7.10).
WORKFLOW_STATE_SCHEMA_VERSION = "1"


class StateSchemaError(ValueError):
    """A serialized workflow state does not match the schema version this code expects."""


class WorkflowStatus(StrEnum):
    """The lifecycle status of one workflow (canonical section 13, plus cancelled)."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


#: Statuses in which the workflow is over; a terminal workflow never runs again.
TERMINAL_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.ESCALATED,
    }
)


@dataclass
class TaskRef:
    """The task this workflow serves."""

    task_id: str
    specification_artifact_id: str | None = None


@dataclass
class StatusBlock:
    """Where the workflow is: status, current stage, and why it terminated (if it did)."""

    state: WorkflowStatus = WorkflowStatus.PENDING
    current_stage: str = "intake"
    termination_reason: str | None = None


@dataclass
class PoliciesBlock:
    """The policies the workflow runs under, recorded so a snapshot is self-describing."""

    termination_policy: str
    approval_policy: str


@dataclass
class ArtifactsBlock:
    """Identifiers of the artifacts the workflow has produced (canonical section 13).

    The review-loop slots (``review_findings``, ``consolidated_review``,
    ``pull_request``) are part of the canonical schema and stay empty until the
    multi-worker modules populate them.
    """

    plan: str | None = None
    patches: list[str] = field(default_factory=list)
    validation_reports: list[str] = field(default_factory=list)
    review_findings: list[str] = field(default_factory=list)
    consolidated_review: str | None = None
    pull_request: str | None = None


@dataclass(frozen=True)
class WorkerInvocation:
    """One worker the workflow invoked, and how that invocation ended."""

    run_id: str
    worker_type: str
    stage: str
    status: str


@dataclass
class WorkersBlock:
    """Every worker invocation, in order."""

    invocations: list[WorkerInvocation] = field(default_factory=list)


@dataclass
class BudgetsBlock:
    """What the workflow has consumed so far."""

    monetary_used: float = 0.0
    token_used: int = 0
    elapsed_seconds: float = 0.0
    worker_count: int = 0
    retry_count: int = 0


@dataclass(frozen=True)
class ApprovalRecord:
    """One resolved (or still pending) approval at a workflow boundary."""

    action: str
    stage: str
    decision: str


@dataclass
class ApprovalsBlock:
    """Approvals the workflow is waiting on, and those already decided."""

    pending: list[ApprovalRecord] = field(default_factory=list)
    resolved: list[ApprovalRecord] = field(default_factory=list)


@dataclass(frozen=True)
class FailureEvent:
    """One recorded failure: the stage it happened in and the reason."""

    stage: str
    reason: str


@dataclass
class FailuresBlock:
    """Every recorded failure, in order."""

    events: list[FailureEvent] = field(default_factory=list)


@dataclass
class CheckpointsBlock:
    """The latest checkpoint identifier, set every time a snapshot is persisted."""

    latest: str | None = None


@dataclass
class WorkflowState:
    """One workflow's explicit, versioned state (canonical-reference.md section 13)."""

    workflow_id: str
    workflow_type: str
    workflow_version: str
    task: TaskRef
    status: StatusBlock
    policies: PoliciesBlock
    artifacts: ArtifactsBlock = field(default_factory=ArtifactsBlock)
    workers: WorkersBlock = field(default_factory=WorkersBlock)
    budgets: BudgetsBlock = field(default_factory=BudgetsBlock)
    approvals: ApprovalsBlock = field(default_factory=ApprovalsBlock)
    failures: FailuresBlock = field(default_factory=FailuresBlock)
    checkpoints: CheckpointsBlock = field(default_factory=CheckpointsBlock)
    schema_version: str = WORKFLOW_STATE_SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the JSON-shaped payload snapshots and trace events carry."""
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "workflow_version": self.workflow_version,
            "task": {
                "task_id": self.task.task_id,
                "specification_artifact_id": self.task.specification_artifact_id,
            },
            "status": {
                "state": self.status.state.value,
                "current_stage": self.status.current_stage,
                "termination_reason": self.status.termination_reason,
            },
            "policies": {
                "termination_policy": self.policies.termination_policy,
                "approval_policy": self.policies.approval_policy,
            },
            "artifacts": {
                "plan": self.artifacts.plan,
                "patches": list(self.artifacts.patches),
                "validation_reports": list(self.artifacts.validation_reports),
                "review_findings": list(self.artifacts.review_findings),
                "consolidated_review": self.artifacts.consolidated_review,
                "pull_request": self.artifacts.pull_request,
            },
            "workers": {
                "invocations": [
                    {
                        "run_id": inv.run_id,
                        "worker_type": inv.worker_type,
                        "stage": inv.stage,
                        "status": inv.status,
                    }
                    for inv in self.workers.invocations
                ],
            },
            "budgets": {
                "monetary_used": self.budgets.monetary_used,
                "token_used": self.budgets.token_used,
                "elapsed_seconds": self.budgets.elapsed_seconds,
                "worker_count": self.budgets.worker_count,
                "retry_count": self.budgets.retry_count,
            },
            "approvals": {
                "pending": [_approval_payload(record) for record in self.approvals.pending],
                "resolved": [_approval_payload(record) for record in self.approvals.resolved],
            },
            "failures": {
                "events": [
                    {"stage": event.stage, "reason": event.reason} for event in self.failures.events
                ],
            },
            "checkpoints": {"latest": self.checkpoints.latest},
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> WorkflowState:
        """Deserialize one payload back into a WorkflowState.

        Raises ``StateSchemaError`` when the payload's ``schema_version`` differs from
        ``WORKFLOW_STATE_SCHEMA_VERSION`` - version drift must fail loudly, never be
        silently migrated (spec 7.10).
        """
        version = str(data.get("schema_version"))
        if version != WORKFLOW_STATE_SCHEMA_VERSION:
            raise StateSchemaError(
                f"workflow state schema version {version!r} does not match the expected "
                f"version {WORKFLOW_STATE_SCHEMA_VERSION!r}; refusing to load"
            )
        task = dict(data["task"])
        status = dict(data["status"])
        policies = dict(data["policies"])
        artifacts = dict(data["artifacts"])
        workers = dict(data["workers"])
        budgets = dict(data["budgets"])
        approvals = dict(data["approvals"])
        failures = dict(data["failures"])
        checkpoints = dict(data["checkpoints"])
        return cls(
            workflow_id=str(data["workflow_id"]),
            workflow_type=str(data["workflow_type"]),
            workflow_version=str(data["workflow_version"]),
            task=TaskRef(
                task_id=str(task["task_id"]),
                specification_artifact_id=task.get("specification_artifact_id"),
            ),
            status=StatusBlock(
                state=WorkflowStatus(str(status["state"])),
                current_stage=str(status["current_stage"]),
                termination_reason=status.get("termination_reason"),
            ),
            policies=PoliciesBlock(
                termination_policy=str(policies["termination_policy"]),
                approval_policy=str(policies["approval_policy"]),
            ),
            artifacts=ArtifactsBlock(
                plan=artifacts.get("plan"),
                patches=[str(item) for item in artifacts.get("patches", [])],
                validation_reports=[str(item) for item in artifacts.get("validation_reports", [])],
                review_findings=[str(item) for item in artifacts.get("review_findings", [])],
                consolidated_review=artifacts.get("consolidated_review"),
                pull_request=artifacts.get("pull_request"),
            ),
            workers=WorkersBlock(
                invocations=[
                    WorkerInvocation(
                        run_id=str(item["run_id"]),
                        worker_type=str(item["worker_type"]),
                        stage=str(item["stage"]),
                        status=str(item["status"]),
                    )
                    for item in workers.get("invocations", [])
                ],
            ),
            budgets=BudgetsBlock(
                monetary_used=float(budgets["monetary_used"]),
                token_used=int(budgets["token_used"]),
                elapsed_seconds=float(budgets["elapsed_seconds"]),
                worker_count=int(budgets["worker_count"]),
                retry_count=int(budgets["retry_count"]),
            ),
            approvals=ApprovalsBlock(
                pending=[_approval_record(item) for item in approvals.get("pending", [])],
                resolved=[_approval_record(item) for item in approvals.get("resolved", [])],
            ),
            failures=FailuresBlock(
                events=[
                    FailureEvent(stage=str(item["stage"]), reason=str(item["reason"]))
                    for item in failures.get("events", [])
                ],
            ),
            checkpoints=CheckpointsBlock(latest=checkpoints.get("latest")),
        )


def _approval_payload(record: ApprovalRecord) -> dict[str, str]:
    return {"action": record.action, "stage": record.stage, "decision": record.decision}


def _approval_record(item: dict[str, Any]) -> ApprovalRecord:
    return ApprovalRecord(
        action=str(item["action"]), stage=str(item["stage"]), decision=str(item["decision"])
    )


def initial_workflow_state(
    workflow_id: str,
    *,
    workflow_type: str,
    workflow_version: str,
    task_id: str,
    termination_policy: str,
    approval_policy: str,
) -> WorkflowState:
    """The state a brand-new workflow starts from: pending, at the intake stage."""
    return WorkflowState(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        workflow_version=workflow_version,
        task=TaskRef(task_id=task_id),
        status=StatusBlock(),
        policies=PoliciesBlock(
            termination_policy=termination_policy,
            approval_policy=approval_policy,
        ),
    )
