"""Sandbox manager: isolated git-worktree lifecycle for write runs (spec 7.7; Lesson 3.2).

All write-capable work happens inside an isolated git worktree of the target clone, on a
temporary branch, so the canonical working copy is never the thing being changed. The
manager owns the whole lifecycle:

* ``create`` adds a worktree of the target at its current revision on a fresh branch;
* ``rollback`` restores a worktree to the starting revision (tracked changes reset,
  untracked files removed) and returns a rollback record naming what was discarded;
* ``destroy`` removes the worktree and its temporary branch when the run is over.

Two refusals are the security boundary (Lesson 3.2: allowed repository root):

* the target must be the root of a real git working tree - not a subdirectory, not an
  arbitrary directory; and
* the target must never be the harness platform repository itself. The write agent
  operates on course TARGET repositories (e.g. the coursectl clone under
  ``workspace/ai-native-sweng-bookit``), never on the repository that contains the
  harness. ``create`` refuses rather than trusting callers to point it well.

Worktrees are created next to the target clone under ``.anse-worktrees/`` so
``coursectl reset`` (which removes every linked worktree of a clone) cleans them up.

SCAFFOLDING: the data contracts and the ``_git`` helper are supplied; implement
``create``, ``rollback``, and ``destroy`` in Module 3, Lessons 3.2 and 3.6.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class SandboxError(Exception):
    """The sandbox lifecycle was violated (bad target, failed git operation)."""


@dataclass(frozen=True)
class Sandbox:
    """One isolated write workspace: a linked worktree of the target on its own branch."""

    #: Root of the target clone the worktree was created from.
    target_root: Path
    #: Root of the isolated worktree; the only place a write run may touch.
    worktree: Path
    #: Temporary branch the worktree is on.
    branch: str
    #: Revision the worktree started from; rollback restores exactly this state.
    base_revision: str


@dataclass(frozen=True)
class RollbackRecord:
    """What a rollback did: the revision restored and the paths it discarded."""

    restored_revision: str
    discarded_paths: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """Serialize for trace payloads (artifact_created: rollback_record)."""
        return {
            "artifact_type": "rollback_record",
            "restored_revision": self.restored_revision,
            "discarded_paths": list(self.discarded_paths),
        }


def _git(cwd: Path, *args: str) -> str:
    """Run one git command, returning stdout or raising ``SandboxError``."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise SandboxError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


class SandboxManager:
    """Creates, rolls back, and destroys isolated worktrees of one target clone."""

    def __init__(self, target_root: Path) -> None:
        self._target = target_root.resolve()

    def create(self, run_id: str) -> Sandbox:
        """Create an isolated worktree for one run on branch ``anse/<run_id>``.

        Refuses when the target is not the root of a git working tree, when it is the
        harness platform repository, or when the run's worktree already exists.
        """
        raise NotImplementedError(
            "Module 3, Lesson 3.2: refuse (SandboxError) unless the target is the root "
            "of a git working tree (git rev-parse --show-toplevel) and is not the "
            "harness platform repository (src/anse_harness present); then record HEAD "
            "as the base revision, add a worktree on branch anse/<run_id> under "
            "<target parent>/.anse-worktrees/, and return the Sandbox."
        )

    def rollback(self, sandbox: Sandbox) -> RollbackRecord:
        """Restore the worktree to its starting revision and report what was discarded.

        Tracked modifications are reset and untracked files are removed, so a failed or
        abandoned run leaves a workspace identical to the one it started with (Lesson
        3.6). Traces live outside the worktree and are preserved untouched.
        """
        raise NotImplementedError(
            "Module 3, Lesson 3.6: collect the dirty paths from git status --porcelain, "
            "hard-reset the worktree to the base revision, clean untracked files, and "
            "return a RollbackRecord naming what was discarded."
        )

    def destroy(self, sandbox: Sandbox) -> None:
        """Remove the worktree and its temporary branch (reset and cleanup, Lesson 3.2)."""
        raise NotImplementedError(
            "Module 3, Lesson 3.2: remove the worktree (git worktree remove --force), "
            "prune stale worktree entries, and delete the temporary branch."
        )
