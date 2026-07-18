"""Integration: deterministic assembly of parallel worker patches (arch-ref 37-38).

Parallel workers produce independent patches against a shared base revision; nothing
merges them implicitly. Integration is its own deterministic step (Lesson 6.9): verify
that every patch was produced from the same base revision, detect and classify
overlapping changes BEFORE applying anything, then apply the patches to a dedicated
integration worktree in graph order - capturing the integrated diff after every
successful apply - and reject, with evidence, any patch that conflicts at the hunk
level. The orchestrator never accepts "last writer wins" (arch-ref 37).

The integration worktree is an ordinary ``SandboxManager`` worktree: the sandbox layer
is unchanged from Module 3, and everything integration adds is additive. Recovery from
a conflicted apply is a hard reset - ``SandboxManager.rollback`` - because git cannot
check out over unmerged paths; the captured integrated diff is what makes recovery
possible without losing the patches already applied.

Overlap classification (arch-ref 38) is deterministic configuration, not judgment:

* ``safe`` - all overlapping paths match the policy's safe suffixes (documentation,
  generated lockfiles); integrate automatically, validation still runs.
* ``prohibited`` - any overlapping path is protected by the policy; replan or
  escalate, never apply.
* ``review_required`` - everything else: same implementation file, shared interface,
  configuration. Integration may proceed hunk by hunk, but a hunk-level conflict is
  rejected with evidence rather than resolved silently.

SCAFFOLDING: the data contracts, the ``changed_paths``/``apply_patch``/``staged_diff``
helpers, and the policy are supplied; implement ``classify_overlap``,
``detect_overlaps``, and ``integrate_patches`` in Module 6, Lesson 6.9.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from anse_harness.runtime.sandbox import Sandbox, SandboxManager


class IntegrationError(Exception):
    """Integration cannot proceed (base-revision drift, unrecoverable worktree)."""


class OverlapClass(StrEnum):
    """The overlap classification vocabulary (arch-ref 38)."""

    SAFE = "safe"
    REVIEW_REQUIRED = "review_required"
    PROHIBITED = "prohibited"


@dataclass(frozen=True)
class OverlapPolicy:
    """Deterministic overlap classification configuration (arch-ref 38)."""

    #: Overlapping paths ending in one of these are safe to integrate automatically.
    safe_suffixes: tuple[str, ...] = (".md",)
    #: Repository-relative paths protected from concurrent modification entirely.
    prohibited_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkerPatch:
    """One worker's patch, carrying the base revision it was produced from."""

    worker_id: str
    patch: str
    base_revision: str


@dataclass(frozen=True)
class PatchOverlap:
    """Two patches that change one or more of the same paths, classified."""

    first_worker: str
    second_worker: str
    paths: tuple[str, ...]
    classification: OverlapClass

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the integration artifact."""
        return {
            "first_worker": self.first_worker,
            "second_worker": self.second_worker,
            "paths": list(self.paths),
            "classification": self.classification.value,
        }


@dataclass(frozen=True)
class ConflictRecord:
    """One rejected patch: the hunk-level conflict evidence integration collected."""

    worker_id: str
    #: stderr of the failed ``git apply`` - names the file and hunk that conflicted.
    error: str
    #: Paths left unmerged by the ``git apply --3way`` evidence probe.
    conflicted_paths: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the integration artifact."""
        return {
            "worker_id": self.worker_id,
            "error": self.error,
            "conflicted_paths": list(self.conflicted_paths),
        }


@dataclass(frozen=True)
class IntegrationStep:
    """One successful apply: the worker and the integrated diff captured after it."""

    worker_id: str
    integrated_diff: str


@dataclass(frozen=True)
class IntegrationResult:
    """The outcome of one integration round over the integration worktree.

    The ``sandbox`` stays alive on return - reviewers inspect the integrated result
    in it - and the CALLER destroys it when the workflow reaches a terminal stage.
    """

    sandbox: Sandbox
    base_revision: str
    #: Worker ids whose patches applied cleanly, in application (graph) order.
    applied: tuple[str, ...]
    rejected: tuple[ConflictRecord, ...]
    #: The integrated diff captured after each successful apply, in order.
    steps: tuple[IntegrationStep, ...]
    #: The integrated diff after the last successful apply ("" when nothing applied).
    integrated_diff: str

    @property
    def ok(self) -> bool:
        """True when every patch applied cleanly."""
        return not self.rejected

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the integration artifact (the worktree itself is not state)."""
        return {
            "artifact_type": "integration_report",
            "base_revision": self.base_revision,
            "applied": list(self.applied),
            "rejected": [record.to_payload() for record in self.rejected],
            "integrated_diff": self.integrated_diff,
            "ok": self.ok,
        }


def changed_paths(diff: str) -> tuple[str, ...]:
    """The repository-relative paths a unified diff touches, in order of appearance.

    Reads both ``--- a/`` and ``+++ b/`` headers so deletions and creations are both
    covered; ``/dev/null`` is never a path. This is the overlap-detection primitive.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[len("+++ b/") :]
        elif line.startswith("--- a/"):
            path = line[len("--- a/") :]
        else:
            continue
        if path != "/dev/null" and path not in seen:
            seen.add(path)
            paths.append(path)
    return tuple(paths)


def apply_patch(
    worktree: Path, patch: str, *, three_way: bool = False
) -> subprocess.CompletedProcess[str]:
    """Apply one unified diff to the worktree AND its index (``git apply --index``).

    Returns the completed process without raising: a non-zero exit is the hunk-level
    conflict signal integration acts on. ``three_way`` re-attempts with
    ``git apply --3way``, which leaves conflicted paths unmerged in the index - the
    conflict EVIDENCE - and requires a hard reset (``SandboxManager.rollback``) to
    recover, because git cannot check out over unmerged paths.
    """
    args = ["git", "apply", "--index"]
    if three_way:
        args.append("--3way")
    return subprocess.run(
        args,
        cwd=worktree,
        input=patch,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def staged_diff(worktree: Path) -> str:
    """The worktree's staged (index vs HEAD) diff: the integrated diff capture.

    ``apply_patch`` stages what it applies, so this is the full integrated change
    after any number of applies; ``--full-index`` keeps it byte-stable across git
    versions, exactly like the Module 3 patch artifact.
    """
    proc = subprocess.run(
        ["git", "diff", "--cached", "--full-index", "--no-color"],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise IntegrationError(f"git diff --cached failed: {proc.stderr.strip()}")
    return proc.stdout


def unmerged_paths(worktree: Path) -> tuple[str, ...]:
    """Paths the index currently holds in an unmerged state (3-way conflict evidence)."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise IntegrationError(f"git diff --diff-filter=U failed: {proc.stderr.strip()}")
    return tuple(line for line in proc.stdout.splitlines() if line)


def classify_overlap(paths: Sequence[str], policy: OverlapPolicy) -> OverlapClass:
    """Classify one set of overlapping paths under the policy (arch-ref 38).

    ``prohibited`` when any path is protected; otherwise ``safe`` when every path
    matches a safe suffix; otherwise ``review_required``. Prohibition dominates -
    a single protected path makes the whole overlap prohibited.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.9: return PROHIBITED if any path is in "
        "policy.prohibited_paths; else SAFE if every path ends with one of "
        "policy.safe_suffixes; else REVIEW_REQUIRED."
    )


def detect_overlaps(
    patches: Sequence[WorkerPatch], *, policy: OverlapPolicy
) -> tuple[PatchOverlap, ...]:
    """Detect and classify every pairwise file-level overlap among the patches.

    Compares the ``changed_paths`` of every pair in application order and reports
    each pair that shares at least one path, classified under the policy. File-level
    intersection is the DETECTION step; hunk-level conflicts within a
    review-required overlap surface at apply time (Lesson 6.9).
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.9: for every pair (i, j) with i < j in patch order, "
        "intersect changed_paths(patches[i].patch) with changed_paths("
        "patches[j].patch) preserving the first patch's path order; report each "
        "non-empty intersection as a PatchOverlap classified by classify_overlap."
    )


def integrate_patches(
    manager: SandboxManager,
    run_id: str,
    patches: Sequence[WorkerPatch],
    *,
    expected_base_revision: str | None = None,
) -> IntegrationResult:
    """Apply worker patches in order onto a fresh integration worktree (arch-ref 37).

    Creates the integration worktree through the UNCHANGED sandbox manager, verifies
    that every patch's ``base_revision`` (and ``expected_base_revision``, when given)
    matches the worktree's base revision - destroying the worktree and raising
    ``IntegrationError`` on drift - then applies each patch with ``apply_patch`` in
    the given order.

    After every successful apply the integrated diff is captured (``staged_diff``):
    a later conflict must not lose the patches already applied. A patch that fails
    to apply is REJECTED with evidence: the apply error, plus the unmerged paths a
    ``--3way`` re-attempt leaves behind; the worktree is then recovered by
    ``SandboxManager.rollback`` (hard reset - the only recovery from unmerged
    paths) and the captured integrated diff is re-applied before integration
    continues with the next patch.

    Returns the result with the worktree ALIVE; the caller owns its destruction.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.9: create the worktree via manager.create(run_id); "
        "verify base revisions; apply each patch with apply_patch, capturing "
        "staged_diff after each success as an IntegrationStep; on failure collect "
        "ConflictRecord evidence (apply stderr + unmerged_paths after a --3way "
        "re-attempt), recover via manager.rollback and re-apply the captured "
        "integrated diff, and continue; return the IntegrationResult with the "
        "sandbox alive."
    )
