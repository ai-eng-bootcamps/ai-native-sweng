"""The worker runtime: short-lived, contract-bounded worker execution (spec 7.8).

Module 6's workers are not new loops - they are the Module 2/3/4 loops instantiated
FRESH, per worker, under a contract (``workers/contract.py``), each in its own trace
scope and (for write-capable workers) its own isolated worktree:

* an IMPLEMENTATION worker is Module 5's investigate + implement pattern under a
  worker-scoped run id, run entirely inside the worker's OWN worktree: a Module 4
  context packet and read-only investigation over that worktree at the shared base
  revision, then a Module 3 write run in the same worktree - N concurrent workers
  never read the shared clone's working tree at all;
* a REVIEW worker is a fresh Module 4 context-driven investigation over the
  INTEGRATED worktree - it receives the task specification, acceptance criteria,
  integrated diff, and validation results, and never the implementer's reasoning
  history (arch-ref 43); its findings come back as structured ``FINDING:`` lines;
* a FIX worker is a fresh Module 3 write run whose sandbox is first brought to the
  current integrated revision and whose task is rendered from the ACCEPTED findings
  and their evidence - never the review conversation (arch-ref 46).

Worker-scoped identity is what makes the whole fan-out replayable: every loop a worker
runs is traced under ``run-<workflow>-<worker>-<stage>-<attempt>`` into that worker's
OWN trace file, so each worker replays independently from its own file through its own
``ReplayAdapter``, in any order, sequentially or concurrently. Event ids are
deterministic per run id, which is exactly why a re-invocation (a review round, a
retry) must bump the attempt segment - reusing a run id would reproduce the previous
attempt's event ids.

The task renderers are PINNED pure functions (the Module 2 discipline): what a worker
is asked is a deterministic function of its inputs, so recorded worker runs replay
byte-stable.

``models/`` and ``tracing/`` are SUPPLIED infrastructure. SCAFFOLDING: the result
contracts and renderers are supplied; implement the three ``run_*_worker`` functions
in Module 6, Lessons 6.4, 6.5, and 6.7.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from anse_harness.approvals.gate import ApprovalGate
from anse_harness.models import ModelAdapter
from anse_harness.review.findings import ReviewFinding
from anse_harness.tracing import TraceWriter
from anse_harness.validation.pipeline import ValidationCheck, ValidationReport
from anse_harness.workers.contract import WorkerContract, WorkerInvocationRecord
from anse_harness.workflows.graph import TaskNode


class WorkerError(Exception):
    """A worker invocation cannot proceed (bad inputs, integrated state unavailable)."""


def head_revision(repo_root: Path) -> str:
    """The repository's current HEAD revision (the shared fan-out base)."""
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise WorkerError(f"cannot read HEAD of {repo_root}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def validation_summary_from_report(report: ValidationReport) -> str:
    """A deterministic one-line-per-check summary reviewers receive (arch-ref 43)."""
    lines = []
    for result in report.results:
        outcome = "ok" if result.ok else f"failed (exit {result.exit_code})"
        lines.append(f"{result.name}: {outcome}")
    return "\n".join(lines)


def render_worker_task(node: TaskNode, investigation_answer: str) -> str:
    """Render one implementation worker's write task (pinned; replay surface)."""
    criteria = "".join(f"- {item}\n" for item in node.acceptance_criteria)
    owned = "".join(f"- {item}\n" for item in node.owned_paths)
    return (
        f"Sub-task {node.worker_id}: {node.description}\n"
        "Acceptance criteria:\n"
        f"{criteria}"
        "Owned paths (change only these):\n"
        f"{owned}"
        "Investigation summary:\n"
        f"{investigation_answer}\n"
    )


def render_review_task(
    concern: str,
    description: str,
    acceptance_criteria: Sequence[str],
    integrated_diff: str,
    validation_summary: str,
) -> str:
    """Render one reviewer's task (pinned; replay surface).

    Carries exactly what a fresh reviewer receives (arch-ref 43): the task, the
    acceptance criteria, the integrated diff, and the validation results - plus the
    structured-output contract the finding parser expects.
    """
    criteria = "".join(f"- {item}\n" for item in acceptance_criteria)
    return (
        f"Review the integrated change for {concern} defects. You are a fresh "
        "reviewer: you have no implementer history, and your job is evidence, not "
        "reassurance.\n"
        f"Feature under review: {description}\n"
        "Acceptance criteria:\n"
        f"{criteria}"
        "Deterministic validation results:\n"
        f"{validation_summary}\n"
        "Integrated diff (already applied to this worktree):\n"
        f"{integrated_diff}\n"
        "Report each defect you can support with evidence as one line:\n"
        'FINDING: {"category": "...", "severity": "...", "confidence": "...", '
        '"summary": "...", "evidence": {"files": [], "lines": [], "tests": [], '
        '"reasoning": "..."}, "impact": "...", "recommended_action": "...", '
        '"deduplication_key": "..."}\n'
        "Do not report style preferences as defects. Finish with exactly one line:\n"
        "CONCLUSION: approved | changes_required | insufficient_evidence\n"
    )


def render_fix_task(findings: Sequence[ReviewFinding], acceptance_criteria: Sequence[str]) -> str:
    """Render one fix worker's task from accepted findings (pinned; replay surface).

    The fix worker receives the findings WITH their evidence and the feature's
    acceptance criteria - and nothing of the review conversation (arch-ref 46).
    """
    blocks = []
    for finding in findings:
        evidence = finding.evidence
        files = ", ".join(evidence.files) if evidence.files else "(none)"
        lines = ", ".join(evidence.lines) if evidence.lines else "(none)"
        blocks.append(
            f"Finding {finding.finding_id} ({finding.category}, severity "
            f"{finding.severity}):\n"
            f"  {finding.summary}\n"
            f"  Evidence files: {files}\n"
            f"  Evidence lines: {lines}\n"
            f"  Evidence reasoning: {evidence.reasoning}\n"
            f"  Recommended action: {finding.recommended_action}\n"
        )
    criteria = "".join(f"- {item}\n" for item in acceptance_criteria)
    return (
        "Resolve the following accepted review findings on the current integrated "
        "change. You receive the findings and their evidence only - not the review "
        "conversation.\n"
        + "".join(blocks)
        + "Acceptance criteria for the feature:\n"
        + criteria
        + "Make the smallest change that resolves the findings; do not modify "
        "unrelated code.\n"
    )


@dataclass(frozen=True)
class ImplementationWorkerResult:
    """One implementation worker's outcome: its patch, evidence, and lineage record."""

    worker_id: str
    #: Final run status of the decisive loop (``RunStatus`` value).
    status: str
    investigation_answer: str | None
    #: The approved, validated patch; None on every failure path (worktree rolled back).
    patch: str | None
    #: Revision the worker's sandbox started from (the integration base check input).
    base_revision: str | None
    validation_report: ValidationReport | None
    cost_usd: float
    #: The canonical 9.2 lineage record (``result`` is filled in by the orchestrator
    #: once the patch artifact id exists).
    invocation: WorkerInvocationRecord


@dataclass(frozen=True)
class ReviewWorkerResult:
    """One review worker's outcome: structured findings and an explicit conclusion."""

    reviewer_id: str
    status: str
    findings: tuple[ReviewFinding, ...]
    conclusion: str
    answer: str
    cost_usd: float
    invocation: WorkerInvocationRecord


@dataclass(frozen=True)
class FixWorkerResult:
    """One fix worker's outcome: the fix delta against the integrated revision."""

    fixer_id: str
    status: str
    #: The fix's own diff relative to the integrated state it was seeded with;
    #: None on every failure path.
    fix_patch: str | None
    validation_report: ValidationReport | None
    cost_usd: float
    invocation: WorkerInvocationRecord


def run_implementation_worker(
    node: TaskNode,
    task_id: str,
    target_root: Path,
    adapter: ModelAdapter,
    *,
    gate: ApprovalGate,
    checks: Sequence[ValidationCheck],
    contract: WorkerContract,
    workflow_id: str = "wf-m06-multiworker",
    attempt: int = 1,
    token_budget: int = 8000,
    model_configuration: str = "scripted",
    tracer: TraceWriter | None = None,
    clock: Callable[[], str] | None = None,
) -> ImplementationWorkerResult:
    """Run one fresh implementation worker for one task-graph node (Lesson 6.4).

    The Module 5 stage pattern under a worker-scoped identity, run ENTIRELY inside
    the worker's own worktree: the sandbox (branch
    ``anse/<workflow>-<worker>-implement-<attempt>``) is created first, the Module 4
    context packet and investigation run over that worktree (run id
    ``run-<workflow>-<worker>-investigate-<attempt>``), and the Module 3 write run
    follows in the same worktree - so N concurrent workers never read the shared
    clone's working tree at all (arch-ref 35: one execution directory per worker).
    Both loops are traced through ``StageTraceWriter`` into the worker's own trace
    file; the contract supplies their iteration and cost limits, and the worker's
    cost is the sum of both loops' costs. An investigation that does not complete
    skips the write phase and reports that status.

    Worktree creation and removal under live fan-out can transiently contend on
    git's repository-level locks: a ``SandboxError`` there is retryable with a
    short backoff - EXCEPT the "already exists" refusal, which is the worker-id
    collision guard and must stay loud.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.4: create the sandbox first (bounded retries on "
        "transient SandboxError; 'already exists' stays loud); build the packet "
        "over the worker's worktree at the sandbox base revision (task id "
        "'<task>/<worker>', the node's description, criteria, and search terms, "
        "worker_type 'implementer'); run the investigation under the worker-scoped "
        "run id with a registry rooted in the worktree; on completion render the "
        "worker task and run the write task in the same worktree; destroy the "
        "sandbox (retry transient failures); return the result with the canonical "
        "9.2 invocation record."
    )


def run_review_worker(
    reviewer_id: str,
    concern: str,
    task_id: str,
    description: str,
    acceptance_criteria: Sequence[str],
    integration_root: Path,
    integrated_diff: str,
    validation_summary: str,
    adapter: ModelAdapter,
    *,
    revision: str,
    contract: WorkerContract,
    workflow_id: str = "wf-m06-multiworker",
    iteration: int = 1,
    token_budget: int = 8000,
    model_configuration: str = "scripted",
    search_terms: Sequence[str] | None = None,
    tracer: TraceWriter | None = None,
    clock: Callable[[], str] | None = None,
) -> ReviewWorkerResult:
    """Run one fresh, read-only review worker over the integrated result (Lesson 6.5).

    A Module 4 context-driven investigation (role profile ``reviewer``) whose packet
    is built over the INTEGRATION worktree and whose task is the pinned review
    request: task specification, acceptance criteria, integrated diff, validation
    results, and the structured-finding contract - and nothing else. The run id is
    ``run-<workflow>-<reviewer>-review-<iteration>``; each review round is a fresh
    invocation with a bumped iteration segment. Findings are parsed from the answer
    with ``findings_from_text``; a run that does not complete reports no findings
    and the conclusion ``insufficient_evidence``.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.5: build the reviewer packet over the integration "
        "worktree (task id '<task>/<reviewer>', description = render_review_task, "
        "worker_type 'reviewer'); run the read-only investigation under the "
        "iteration-scoped run id with the contract's limits; parse findings and "
        "conclusion from the answer; return the result with the canonical 9.2 "
        "invocation record."
    )


def run_fix_worker(
    fixer_id: str,
    findings: Sequence[ReviewFinding],
    task_id: str,
    acceptance_criteria: Sequence[str],
    target_root: Path,
    integrated_diff: str,
    adapter: ModelAdapter,
    *,
    gate: ApprovalGate,
    checks: Sequence[ValidationCheck],
    contract: WorkerContract,
    workflow_id: str = "wf-m06-multiworker",
    attempt: int = 1,
    model_configuration: str = "scripted",
    tracer: TraceWriter | None = None,
) -> FixWorkerResult:
    """Run one fresh fix worker for its assigned accepted findings (Lesson 6.7).

    A Module 3 write run whose sandbox is first brought to the CURRENT integrated
    revision (the integrated diff is applied to the fresh worktree and its index;
    a diff that does not apply raises ``WorkerError`` - the fix must target the
    revision the findings were raised against). The task is rendered from the
    accepted findings and their evidence. Because the integrated diff is staged,
    the write run's patch is exactly the fix's own delta relative to the
    integrated state. The run id is ``run-<workflow>-<fixer>-fix-<attempt>``.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.7: create the sandbox, seed it with the integrated "
        "diff via workflows.integration.apply_patch (raise WorkerError on a "
        "non-zero exit), render the fix task from the findings, run the write "
        "task under the fixer-scoped run id with the contract's limits, destroy "
        "the sandbox, and return the result with the canonical 9.2 invocation "
        "record."
    )
