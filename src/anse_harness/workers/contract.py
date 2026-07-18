"""Worker contracts and invocation records (canonical-reference.md section 9).

A worker is a bounded execution of a model-driven task (spec 7.8). Module 6 turns that
definition into an explicit, written CONTRACT: what the worker is for, what it receives,
what it must produce, which capabilities it may and may not use, and the limits and
criteria under which it runs. The contract is what makes a fresh, short-lived worker a
designed component instead of an ad-hoc prompt - the orchestrator instantiates workers
FROM contracts, and every invocation is recorded against the contract it ran under
(Lessons 6.1 and 6.2).

Two schemas live here, both mirroring the canonical reference exactly:

* ``WorkerContract`` - canonical section 9: purpose, input/output schemas, context
  requirements (required AND excluded - what a worker must NOT see is part of the
  design, Lesson 6.5), allowed/prohibited capabilities, model policy, budgets, limits,
  success/failure criteria, escalation conditions, trace requirements.
* ``WorkerInvocationRecord`` - canonical section 9.2: one execution of a worker under
  its contract. The workflow state's ``workers.invocations`` list keeps the compact
  four-field entries introduced in Module 5; this record is the full lineage document
  and is persisted as a store artifact per invocation (``invocation-<worker>-<stage>-<n>``).

The standard contracts for the Module 6 reference workflow - implementation worker,
specialized reviewers, fix worker - are constructed by the factory functions at the
bottom. Their capability lists name exactly the tools of the Module 5 registries
(``build_investigation_registry`` / ``build_implementation_registry``), so the contract
and the registry a worker actually receives cannot drift apart silently.

SUPPLIED infrastructure: schemas and standard contracts are consumed as-is; the runtime
that executes workers under these contracts (``workers/runner.py``) is yours to
implement in Module 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Tool names of the Module 5 read-only investigation registry, in registration order.
READ_ONLY_CAPABILITIES: tuple[str, ...] = (
    "list_files",
    "search_text",
    "read_file",
    "inspect_git_status",
    "run_read_only_command",
)

#: Tool names of the Module 5 write registry, in registration order.
WRITE_CAPABILITIES: tuple[str, ...] = (
    "list_files",
    "search_text",
    "read_file",
    "inspect_git_status",
    "create_file",
    "replace_text",
    "delete_file",
    "inspect_diff",
    "run_validation_command",
)

#: Capabilities a read-only worker must never hold (the write-capable tool set).
WRITE_ONLY_CAPABILITIES: tuple[str, ...] = tuple(
    name for name in WRITE_CAPABILITIES if name not in READ_ONLY_CAPABILITIES
)


@dataclass(frozen=True)
class ContextRequirements:
    """What a worker's context packet must contain - and must not (canonical section 9).

    The ``excluded`` list is load-bearing: reviewer objectivity comes from what the
    reviewer does NOT receive (implementer reasoning history, prior reviewer
    conclusions), not from asking it to be objective (Lesson 6.5).
    """

    required: tuple[str, ...]
    excluded: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Serialize for artifact payloads."""
        return {"required": list(self.required), "excluded": list(self.excluded)}

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> ContextRequirements:
        """Deserialize from an artifact payload."""
        return cls(
            required=tuple(str(item) for item in data.get("required", [])),
            excluded=tuple(str(item) for item in data.get("excluded", [])),
        )


@dataclass(frozen=True)
class WorkerContract:
    """One worker type's written contract (canonical-reference.md section 9)."""

    worker_type: str
    purpose: str
    #: Names of the inputs the worker receives (canonical 9.1 ``input`` keys).
    input_schema: tuple[str, ...]
    #: Names of the outputs the worker must produce (canonical 9.1 ``output`` keys).
    output_schema: tuple[str, ...]
    context: ContextRequirements
    allowed_capabilities: tuple[str, ...]
    prohibited_capabilities: tuple[str, ...]
    model_policy: str
    time_budget_seconds: int
    cost_budget_usd: float
    iteration_limit: int
    success_criteria: tuple[str, ...]
    failure_criteria: tuple[str, ...]
    escalation_conditions: tuple[str, ...]
    trace_requirements: str

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the worker-contract artifact."""
        return {
            "artifact_type": "worker_contract",
            "worker_type": self.worker_type,
            "purpose": self.purpose,
            "input_schema": list(self.input_schema),
            "output_schema": list(self.output_schema),
            "context": self.context.to_payload(),
            "capabilities": {
                "allowed": list(self.allowed_capabilities),
                "prohibited": list(self.prohibited_capabilities),
            },
            "model_policy": self.model_policy,
            "limits": {
                "time_budget_seconds": self.time_budget_seconds,
                "cost_budget_usd": self.cost_budget_usd,
                "iteration_limit": self.iteration_limit,
            },
            "success_criteria": list(self.success_criteria),
            "failure_criteria": list(self.failure_criteria),
            "escalation_conditions": list(self.escalation_conditions),
            "trace_requirements": self.trace_requirements,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> WorkerContract:
        """Deserialize one worker-contract artifact payload."""
        capabilities = dict(data.get("capabilities", {}))
        limits = dict(data.get("limits", {}))
        return cls(
            worker_type=str(data["worker_type"]),
            purpose=str(data["purpose"]),
            input_schema=tuple(str(item) for item in data.get("input_schema", [])),
            output_schema=tuple(str(item) for item in data.get("output_schema", [])),
            context=ContextRequirements.from_payload(dict(data.get("context", {}))),
            allowed_capabilities=tuple(str(item) for item in capabilities.get("allowed", [])),
            prohibited_capabilities=tuple(str(item) for item in capabilities.get("prohibited", [])),
            model_policy=str(data["model_policy"]),
            time_budget_seconds=int(limits["time_budget_seconds"]),
            cost_budget_usd=float(limits["cost_budget_usd"]),
            iteration_limit=int(limits["iteration_limit"]),
            success_criteria=tuple(str(item) for item in data.get("success_criteria", [])),
            failure_criteria=tuple(str(item) for item in data.get("failure_criteria", [])),
            escalation_conditions=tuple(
                str(item) for item in data.get("escalation_conditions", [])
            ),
            trace_requirements=str(data["trace_requirements"]),
        )


@dataclass(frozen=True)
class WorkerInvocationRecord:
    """One execution of a worker under its contract (canonical-reference.md section 9.2).

    The compact ``WorkerInvocation`` entries in the workflow state stay as Module 5
    defined them; this is the full lineage record, persisted as a store artifact.
    """

    worker_invocation_id: str
    worker_type: str
    assigned_task: str
    model_configuration: str
    context_packet_id: str | None
    available_capabilities: tuple[str, ...]
    status: str
    result: str | None
    cost: float
    duration_seconds: float
    parent_workflow: str
    parent_worker: str | None

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the invocation-record artifact."""
        return {
            "artifact_type": "worker_invocation_record",
            "worker_invocation_id": self.worker_invocation_id,
            "worker_type": self.worker_type,
            "assigned_task": self.assigned_task,
            "model_configuration": self.model_configuration,
            "context_packet_id": self.context_packet_id,
            "available_capabilities": list(self.available_capabilities),
            "status": self.status,
            "result": self.result,
            "cost": self.cost,
            "duration_seconds": self.duration_seconds,
            "parent_workflow": self.parent_workflow,
            "parent_worker": self.parent_worker,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> WorkerInvocationRecord:
        """Deserialize one invocation-record artifact payload."""
        return cls(
            worker_invocation_id=str(data["worker_invocation_id"]),
            worker_type=str(data["worker_type"]),
            assigned_task=str(data["assigned_task"]),
            model_configuration=str(data["model_configuration"]),
            context_packet_id=data.get("context_packet_id"),
            available_capabilities=tuple(
                str(item) for item in data.get("available_capabilities", [])
            ),
            status=str(data["status"]),
            result=data.get("result"),
            cost=float(data["cost"]),
            duration_seconds=float(data["duration_seconds"]),
            parent_workflow=str(data["parent_workflow"]),
            parent_worker=data.get("parent_worker"),
        )


def implementer_contract(
    *, cost_budget_usd: float = 1.0, iteration_limit: int = 8
) -> WorkerContract:
    """The implementation worker's contract: one bounded sub-task, one isolated worktree."""
    return WorkerContract(
        worker_type="implementer",
        purpose=(
            "Implement one bounded sub-task of the decomposed feature inside an "
            "isolated sandbox worktree and surface the change as a patch artifact."
        ),
        input_schema=("task_node", "context_packet"),
        output_schema=("patch_artifact", "validation_report"),
        context=ContextRequirements(
            required=(
                "sub_task_description",
                "acceptance_criteria",
                "owned_paths",
                "relevant_source",
            ),
            excluded=("sibling_worker_conversations", "unrelated_repository_files"),
        ),
        allowed_capabilities=WRITE_CAPABILITIES,
        prohibited_capabilities=("merge", "push", "create_pull_request"),
        model_policy="scripted or replay in course runs; live mode is budget-gated",
        time_budget_seconds=600,
        cost_budget_usd=cost_budget_usd,
        iteration_limit=iteration_limit,
        success_criteria=(
            "the change passes the validation pipeline",
            "the approved patch touches only the sub-task's owned paths",
        ),
        failure_criteria=(
            "validation fails or the patch approval is rejected",
            "an iteration or cost limit stops the run before a patch exists",
        ),
        escalation_conditions=("the cost budget is exhausted before completion",),
        trace_requirements="one trace file per worker invocation, worker-scoped run ids",
    )


def reviewer_contract(
    concern: str, *, cost_budget_usd: float = 1.0, iteration_limit: int = 6
) -> WorkerContract:
    """A fresh, read-only reviewer specialized by concern (arch-ref 42-43).

    ``concern`` is a finding category such as ``correctness``, ``tests``, or
    ``maintainability``; the worker type is ``<concern>_reviewer``.
    """
    return WorkerContract(
        worker_type=f"{concern}_reviewer",
        purpose=(
            f"Identify {concern} defects in the integrated change, with evidence, "
            "as a fresh instance with no implementer reasoning history."
        ),
        input_schema=("task_specification", "integrated_diff", "validation_results"),
        output_schema=("findings", "conclusion"),
        context=ContextRequirements(
            required=(
                "task_specification",
                "acceptance_criteria",
                "integrated_diff",
                "relevant_source",
                "validation_results",
            ),
            excluded=(
                "implementer_reasoning_history",
                "implementer_self_assessment",
                "previous_reviewer_conclusions",
                "fix_worker_conversations",
            ),
        ),
        allowed_capabilities=READ_ONLY_CAPABILITIES,
        prohibited_capabilities=WRITE_ONLY_CAPABILITIES,
        model_policy="scripted or replay in course runs; live mode is budget-gated",
        time_budget_seconds=600,
        cost_budget_usd=cost_budget_usd,
        iteration_limit=iteration_limit,
        success_criteria=(
            "findings use the structured schema",
            "every finding carries evidence",
            "the conclusion is explicit",
        ),
        failure_criteria=("the run ends without an explicit conclusion",),
        escalation_conditions=(
            "requirements are ambiguous",
            "evidence is contradictory",
        ),
        trace_requirements="one trace file per reviewer invocation, worker-scoped run ids",
    )


def fix_worker_contract(
    *, cost_budget_usd: float = 1.0, iteration_limit: int = 8
) -> WorkerContract:
    """A fresh fix worker: accepted findings in, a targeted patch out (arch-ref 46)."""
    return WorkerContract(
        worker_type="fix_worker",
        purpose=(
            "Resolve accepted review findings on the current integrated revision "
            "as a fresh instance, receiving the findings and their evidence - "
            "never the review conversation."
        ),
        input_schema=("accepted_findings", "integrated_diff", "acceptance_criteria"),
        output_schema=("patch_artifact", "validation_report"),
        context=ContextRequirements(
            required=(
                "accepted_findings_with_evidence",
                "affected_files",
                "acceptance_criteria",
                "current_integrated_revision",
            ),
            excluded=(
                "review_conversation",
                "implementer_reasoning_history",
                "unrelated_findings",
            ),
        ),
        allowed_capabilities=WRITE_CAPABILITIES,
        prohibited_capabilities=("merge", "push", "create_pull_request"),
        model_policy="scripted or replay in course runs; live mode is budget-gated",
        time_budget_seconds=600,
        cost_budget_usd=cost_budget_usd,
        iteration_limit=iteration_limit,
        success_criteria=(
            "the assigned findings' defects are resolved",
            "the change passes the validation pipeline",
        ),
        failure_criteria=(
            "validation fails or the patch approval is rejected",
            "the fix does not apply onto the integrated revision",
        ),
        escalation_conditions=("the cost budget is exhausted before completion",),
        trace_requirements="one trace file per fix invocation, worker-scoped run ids",
    )
