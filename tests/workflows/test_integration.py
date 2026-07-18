"""Integration and overlap detection over real worker patches (Lesson 6.9).

Exercises the deterministic integration step (arch-ref 37) and the overlap policy
(arch-ref 38) against a real git repository: ordered ``git apply --index`` onto an
integration worktree, capture-after-each-apply, file-level overlap detection with
classification, hunk-level conflict rejection with evidence, and recovery that keeps
the patches already applied. These fail against the scaffolding stubs and pass once
the integration module is implemented to the reference behaviour.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from anse_harness.runtime.sandbox import SandboxManager
from anse_harness.tools.inspect_diff import worktree_diff
from anse_harness.workflows.integration import (
    IntegrationError,
    OverlapClass,
    OverlapPolicy,
    WorkerPatch,
    classify_overlap,
    detect_overlaps,
    integrate_patches,
    staged_diff,
    unmerged_paths,
)

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m06"

PINNED_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "ANSE Course",
    "GIT_AUTHOR_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_NAME": "ANSE Course",
    "GIT_COMMITTER_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


def _materialize_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "repo", repo)
    env = {**os.environ, **PINNED_COMMIT_ENV}
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "-c", "core.autocrlf=false", "add", "-A"],
        ["git", "commit", "-q", "-m", "Practice fixture baseline"],
    ):
        subprocess.run(args, cwd=repo, env=env, check=True, capture_output=True)
    return repo


def _patch(repo: Path, run_id: str, path: str, old: str, new: str) -> WorkerPatch:
    """Produce one real worker-shaped patch: edit in a worktree, diff, destroy."""
    manager = SandboxManager(repo)
    sandbox = manager.create(run_id)
    try:
        target = sandbox.worktree / path
        target.write_text(target.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        diff = worktree_diff(sandbox.worktree)
    finally:
        manager.destroy(sandbox)
    return WorkerPatch(worker_id=run_id, patch=diff, base_revision=sandbox.base_revision)


@pytest.fixture(name="repo")
def _repo(tmp_path: Path) -> Path:
    return _materialize_repo(tmp_path)


def _disjoint_patches(repo: Path) -> tuple[WorkerPatch, WorkerPatch]:
    first = _patch(
        repo,
        "worker-a",
        "internal/tags/normalize.go",
        "strings.ToLower(tag)",
        'strings.ToLower(strings.TrimLeft(tag, " "))',
    )
    second = _patch(
        repo,
        "worker-b",
        "internal/labels/render.go",
        '"[" + label + "]"',
        '"<" + label + ">"',
    )
    return first, second


def _conflicting_patch(repo: Path) -> WorkerPatch:
    # Edits the same line as worker-a's patch, differently: a hunk-level conflict.
    return _patch(
        repo,
        "worker-x",
        "internal/tags/normalize.go",
        "strings.ToLower(tag)",
        "strings.ToUpper(tag)",
    )


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (("docs/notes.md",), OverlapClass.SAFE),
        (("internal/tags/normalize.go",), OverlapClass.REVIEW_REQUIRED),
        (("docs/notes.md", "internal/tags/normalize.go"), OverlapClass.REVIEW_REQUIRED),
        (("go.mod",), OverlapClass.PROHIBITED),
        (("docs/notes.md", "go.mod"), OverlapClass.PROHIBITED),
    ],
)
def test_overlap_classification_is_deterministic_policy(
    paths: tuple[str, ...], expected: OverlapClass
) -> None:
    policy = OverlapPolicy(safe_suffixes=(".md",), prohibited_paths=("go.mod",))
    assert classify_overlap(paths, policy) is expected


def test_disjoint_patches_report_no_overlap(repo: Path) -> None:
    first, second = _disjoint_patches(repo)
    assert detect_overlaps([first, second], policy=OverlapPolicy()) == ()


def test_overlap_detection_fires_on_a_colliding_pair(repo: Path) -> None:
    first, _ = _disjoint_patches(repo)
    colliding = _conflicting_patch(repo)
    overlaps = detect_overlaps([first, colliding], policy=OverlapPolicy())
    assert len(overlaps) == 1
    assert overlaps[0].first_worker == "worker-a"
    assert overlaps[0].second_worker == "worker-x"
    assert overlaps[0].paths == ("internal/tags/normalize.go",)
    assert overlaps[0].classification is OverlapClass.REVIEW_REQUIRED


def test_integration_applies_in_order_and_captures_after_each_apply(repo: Path) -> None:
    first, second = _disjoint_patches(repo)
    manager = SandboxManager(repo)
    result = integrate_patches(manager, "wf-t-integration-1", [first, second])
    try:
        assert result.ok
        assert result.applied == ("worker-a", "worker-b")
        assert [step.worker_id for step in result.steps] == ["worker-a", "worker-b"]
        # Capture after each apply: the first step's diff has only the first patch.
        assert "normalize.go" in result.steps[0].integrated_diff
        assert "render.go" not in result.steps[0].integrated_diff
        assert "normalize.go" in result.integrated_diff
        assert "render.go" in result.integrated_diff
        # The worktree really carries the integrated change, staged.
        assert staged_diff(result.sandbox.worktree) == result.integrated_diff
    finally:
        manager.destroy(result.sandbox)


def test_conflicting_patch_is_rejected_with_evidence_and_earlier_work_kept(repo: Path) -> None:
    first, second = _disjoint_patches(repo)
    colliding = _conflicting_patch(repo)
    manager = SandboxManager(repo)
    result = integrate_patches(manager, "wf-t-integration-1", [first, colliding, second])
    try:
        assert not result.ok
        assert result.applied == ("worker-a", "worker-b")
        assert len(result.rejected) == 1
        conflict = result.rejected[0]
        assert conflict.worker_id == "worker-x"
        assert "normalize.go" in conflict.error
        assert conflict.conflicted_paths == ("internal/tags/normalize.go",)
        # Recovery kept the patches already applied and left no unmerged paths.
        assert unmerged_paths(result.sandbox.worktree) == ()
        assert "TrimLeft" in result.integrated_diff
        assert "render.go" in result.integrated_diff
        assert "ToUpper" not in result.integrated_diff
        assert staged_diff(result.sandbox.worktree) == result.integrated_diff
    finally:
        manager.destroy(result.sandbox)


def test_integration_refuses_base_revision_drift(repo: Path) -> None:
    first, _ = _disjoint_patches(repo)
    drifted = WorkerPatch(worker_id=first.worker_id, patch=first.patch, base_revision="0" * 40)
    manager = SandboxManager(repo)
    with pytest.raises(IntegrationError, match="refusing to integrate"):
        integrate_patches(manager, "wf-t-integration-1", [drifted])
    # The refused integration left no worktree behind: the same run id is creatable.
    result = integrate_patches(manager, "wf-t-integration-1", [first])
    manager.destroy(result.sandbox)


def test_expected_base_revision_mismatch_refuses(repo: Path) -> None:
    first, _ = _disjoint_patches(repo)
    manager = SandboxManager(repo)
    with pytest.raises(IntegrationError, match="refusing to integrate"):
        integrate_patches(manager, "wf-t-integration-1", [first], expected_base_revision="f" * 40)
