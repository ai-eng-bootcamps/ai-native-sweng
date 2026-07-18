"""Failure classification onto the canonical taxonomy (Lesson 7.1).

Failures are classified BEFORE they are responded to (arch-ref 50): the response -
retry, replan, escalate, terminate - follows from the failure class, never from a
vague label. The fifteen canonical classes come from canonical-reference section 8
and their exact strings are used everywhere a failure is named: trace payloads,
state failure events, artifacts, and reports. Every classification also names the
affected BOUNDARY (model, tool, sandbox, state store, approval, validation,
integration, ...) - canonical section 8's language rule.

Two classifiers cover the two ways a workflow fails:

* ``classify_exception`` - the CRASH path: an exception escaped the engine or a
  worker (provider timeout, tool contract violation, sandbox fault, corrupted
  state). The exception type carries the class.
* ``classify_outcome`` - the TERMINAL path: the engine handled the failure itself
  and produced an explicit failed/escalated/cancelled terminal (malformed plan
  output, failed validation, rejected approval, exhausted budget). The
  ``termination_reason`` carries the class, matched against ``OUTCOME_RULES``.

The classification becomes a persisted artifact (``FailureRecord``) so a failed
run remains diagnosable from its store alone - the Module 7 assessment reads
exactly these records.

SCAFFOLDING: the taxonomy, the rule table, and the record contract are supplied;
implement ``classify_exception`` and ``classify_outcome`` in Module 7, Lesson 7.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anse_harness.workflows.state import WorkflowState

#: The fifteen canonical failure classes (canonical-reference section 8), verbatim.
CANONICAL_FAILURE_CLASSES: tuple[str, ...] = (
    "transient infrastructure failure",
    "model-provider failure",
    "malformed output",
    "tool failure",
    "policy denial",
    "context failure",
    "planning failure",
    "implementation failure",
    "validation failure",
    "review failure",
    "integration conflict",
    "budget exhaustion",
    "approval timeout",
    "insufficient evidence",
    "persistent unknown failure",
)


@dataclass(frozen=True)
class FailureClassification:
    """One classified failure: canonical class, affected boundary, and retry hint.

    ``retryable`` is the SAME-INPUT hint: True only when repeating the identical
    attempt could plausibly succeed (a transient fault). A permanent provider
    error, a tool contract violation, or a corrupted checkpoint would reproduce
    itself, so it carries False even when another retry MODE (revised context,
    replanning) might still apply.
    """

    failure_class: str
    boundary: str
    retryable: bool
    detail: str

    def describe(self) -> str:
        """The canonical one-line description: class, boundary, and detail."""
        return f"{self.failure_class} at the {self.boundary} boundary: {self.detail}"

    def to_payload(self) -> dict[str, Any]:
        """Serialize for trace payloads and artifacts."""
        return {
            "failure_class": self.failure_class,
            "boundary": self.boundary,
            "retryable": self.retryable,
            "detail": self.detail,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> FailureClassification:
        """Deserialize one payload back into a FailureClassification."""
        return cls(
            failure_class=str(data["failure_class"]),
            boundary=str(data["boundary"]),
            retryable=bool(data["retryable"]),
            detail=str(data["detail"]),
        )


#: Ordered termination-reason rules for ``classify_outcome``: the FIRST rule whose
#: substring occurs in the terminal state's ``termination_reason`` decides the
#: (canonical class, boundary) pair. Order matters: more specific reasons first.
OUTCOME_RULES: tuple[tuple[str, str, str], ...] = (
    ("planning produced no steps", "malformed output", "model"),
    ("validation_failed", "validation failure", "validation"),
    ("plan_rejected", "policy denial", "approval"),
    ("patch_approval_rejected", "policy denial", "approval"),
    ("budget exhausted", "budget exhaustion", "budgets"),
    ("no progress", "review failure", "review"),
    ("conflicting findings", "review failure", "review"),
    ("conflict", "integration conflict", "integration"),
    ("review/fix loop stopped", "budget exhaustion", "budgets"),
    ("implementation did not reach validation", "implementation failure", "worker"),
)


@dataclass(frozen=True)
class FailureRecord:
    """The failure-classification artifact: one classified failure, persisted."""

    workflow_id: str
    task_id: str
    stage: str
    attempt: int
    classification: FailureClassification

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the failure-classification artifact."""
        return {
            "artifact_type": "failure_classification",
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "stage": self.stage,
            "attempt": self.attempt,
            "classification": self.classification.to_payload(),
            "description": self.classification.describe(),
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> FailureRecord:
        """Deserialize one artifact payload back into a FailureRecord."""
        return cls(
            workflow_id=str(data["workflow_id"]),
            task_id=str(data["task_id"]),
            stage=str(data["stage"]),
            attempt=int(data["attempt"]),
            classification=FailureClassification.from_payload(dict(data["classification"])),
        )


def failure_artifact_id(task_id: str, index: int) -> str:
    """Deterministic identifier of the nth failure-classification artifact."""
    return f"failure-{task_id}-{index}"


def classify_exception(exc: BaseException) -> FailureClassification:
    """Map a raised exception onto the canonical taxonomy (the crash path).

    The mapping, checked in order (``isinstance``, so subclasses match first):

    * ``ModelTimeoutError`` -> model-provider failure, boundary ``model``,
      retryable True (canonical: a timeout is always retryable);
    * ``ProviderError`` -> model-provider failure, boundary ``model``, retryable
      taken from the error's own ``retryable`` classification;
    * ``ToolError`` -> tool failure, boundary ``tool``, retryable False (tools
      raise only on contract violations; a retry would reproduce the violation);
    * ``SandboxError`` -> transient infrastructure failure, boundary ``sandbox``,
      retryable True (worktree lock contention is the measured case);
    * ``StateSchemaError`` or ``StateStoreError`` -> transient infrastructure
      failure, boundary ``state store``, retryable False (a corrupted or missing
      checkpoint reproduces itself; canonical section 8 has no dedicated
      state-corruption class, so the environment-fault class carries it with the
      boundary naming the store);
    * ``WorkerError`` -> implementation failure, boundary ``worker``, retryable
      False;
    * ``OSError`` -> transient infrastructure failure, boundary ``filesystem``,
      retryable True;
    * anything else -> persistent unknown failure, boundary ``unknown``,
      retryable False.

    ``detail`` is ``str(exc)`` in every case.
    """
    raise NotImplementedError(
        "Module 7, Lesson 7.1: test the exception type in the documented order "
        "(ModelTimeoutError before ProviderError; StateSchemaError/StateStoreError "
        "before OSError) and return the FailureClassification with detail=str(exc)."
    )


def classify_outcome(state: WorkflowState) -> FailureClassification | None:
    """Map a terminal workflow state onto the canonical taxonomy (the handled path).

    Returns None for non-terminal states, for the completed terminal, and for a
    terminal without a ``termination_reason``. Otherwise the reason is matched
    against ``OUTCOME_RULES`` in order; the first rule whose substring occurs in
    the reason decides the class and boundary, and the full reason becomes
    ``detail``. A terminal reason no rule matches is a persistent unknown failure
    at the ``workflow`` boundary. Outcome classifications are never same-input
    retryable: the engine already handled the failure deterministically, so
    ``retryable`` is always False.
    """
    raise NotImplementedError(
        "Module 7, Lesson 7.1: return None unless the state is failed, escalated, "
        "or cancelled with a termination_reason; otherwise scan OUTCOME_RULES in "
        "order for the first substring match and build the classification with "
        "retryable=False and detail=termination_reason."
    )
