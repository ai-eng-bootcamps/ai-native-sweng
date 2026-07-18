"""Contract tests for the sandbox worktree lifecycle (Lesson 3.2, Lesson 3.6).

The sandbox is the isolation boundary: work happens in a linked worktree on a temporary
branch, the canonical clone is never touched, targets that are not real git roots (or
that are the harness itself) are refused, and rollback restores the starting revision.
These fail against the scaffolding stubs and pass once the manager is implemented to
the reference behaviour.
"""

import subprocess
from pathlib import Path

import pytest

from anse_harness.runtime.sandbox import Sandbox, SandboxError, SandboxManager

pytestmark = pytest.mark.student_impl


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """A throwaway target clone with one committed file."""
    repo = tmp_path / "target"
    repo.mkdir()
    (repo / "app.txt").write_text("version one\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


def _create(target: Path) -> tuple[SandboxManager, Sandbox]:
    manager = SandboxManager(target)
    return manager, manager.create("test-run")


# ─── creation: an isolated worktree on a temporary branch ────────────────────────────
def test_create_makes_an_isolated_worktree_of_the_target(target: Path) -> None:
    _, sandbox = _create(target)
    assert sandbox.worktree != target.resolve()
    assert (sandbox.worktree / "app.txt").read_text(encoding="utf-8") == "version one\n"
    assert sandbox.branch == "anse/test-run"
    assert sandbox.base_revision == _git(target, "rev-parse", "HEAD").strip()
    # The target's own working tree is untouched by sandbox creation.
    assert _git(target, "status", "--porcelain") == ""


def test_writes_in_the_worktree_never_touch_the_target(target: Path) -> None:
    _, sandbox = _create(target)
    (sandbox.worktree / "app.txt").write_text("changed in sandbox\n", encoding="utf-8")
    assert (target / "app.txt").read_text(encoding="utf-8") == "version one\n"
    assert _git(target, "status", "--porcelain") == ""


# ─── refusals: the allowed repository root is enforced, not assumed ──────────────────
def test_create_refuses_a_directory_that_is_not_a_git_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(SandboxError):
        SandboxManager(plain).create("test-run")


def test_create_refuses_a_subdirectory_of_a_repo(target: Path) -> None:
    sub = target / "internal"
    sub.mkdir()
    with pytest.raises(SandboxError):
        SandboxManager(sub).create("test-run")


def test_create_refuses_the_harness_platform_repository(target: Path) -> None:
    # A repo that carries the harness package is the platform repo, never a target.
    (target / "src" / "anse_harness").mkdir(parents=True)
    with pytest.raises(SandboxError):
        SandboxManager(target).create("test-run")


# ─── rollback: the starting revision comes back, with a record ───────────────────────
def test_rollback_restores_a_dirtied_worktree(target: Path) -> None:
    manager, sandbox = _create(target)
    (sandbox.worktree / "app.txt").write_text("broken\n", encoding="utf-8")
    (sandbox.worktree / "stray.txt").write_text("leftover\n", encoding="utf-8")

    record = manager.rollback(sandbox)

    assert record.restored_revision == sandbox.base_revision
    assert set(record.discarded_paths) == {"app.txt", "stray.txt"}
    assert (sandbox.worktree / "app.txt").read_text(encoding="utf-8") == "version one\n"
    assert not (sandbox.worktree / "stray.txt").exists()
    assert _git(sandbox.worktree, "status", "--porcelain") == ""


def test_rollback_of_a_clean_worktree_discards_nothing(target: Path) -> None:
    manager, sandbox = _create(target)
    record = manager.rollback(sandbox)
    assert record.discarded_paths == ()


# ─── destroy: reset and cleanup ──────────────────────────────────────────────────────
def test_destroy_removes_the_worktree_and_its_branch(target: Path) -> None:
    manager, sandbox = _create(target)
    manager.destroy(sandbox)
    assert not sandbox.worktree.exists()
    branches = _git(target, "branch", "--list", sandbox.branch)
    assert branches.strip() == ""
