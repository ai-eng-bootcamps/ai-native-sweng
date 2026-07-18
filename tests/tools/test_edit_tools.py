"""Contract tests for the narrow edit tools (Lesson 3.3: safe edit tools).

Each edit capability is narrow, typed, and bounded: paths are confined to the sandbox
worktree, edits are size-bounded, replace demands a unique match, deletion demands
approval, and the diff is inspectable. These fail against the scaffolding stubs and pass
once the tools are implemented to the reference behaviour.
"""

import subprocess
from pathlib import Path

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all
from anse_harness.tools.base import ToolError
from anse_harness.tools.create_file import CreateFileTool
from anse_harness.tools.delete_file import DeleteFileTool
from anse_harness.tools.inspect_diff import InspectDiffTool
from anse_harness.tools.read_file import PathValidationError
from anse_harness.tools.replace_text import ReplaceTextTool
from anse_harness.tools.write_guards import MAX_EDIT_BYTES, EditSizeError

pytestmark = pytest.mark.student_impl


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A throwaway git worktree with one committed file."""
    repo = tmp_path / "worktree"
    repo.mkdir()
    (repo / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "base"],
    ):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)
    return repo


# ─── contract: side-effect classes and serializable specs ────────────────────────────
def test_edit_tool_contracts_declare_their_side_effects(worktree: Path) -> None:
    gate = ApprovalGate(approve_all)
    assert CreateFileTool(worktree).side_effect_class == 1
    assert ReplaceTextTool(worktree).side_effect_class == 1
    assert DeleteFileTool(worktree, gate).side_effect_class == 2  # delete needs approval
    assert InspectDiffTool(worktree).side_effect_class == 0
    for tool in (CreateFileTool(worktree), ReplaceTextTool(worktree)):
        spec = tool.to_spec()
        assert spec.name == tool.name
        assert spec.input_schema["additionalProperties"] is False
    # Exercise an implementation path too, not only the supplied contract.
    assert CreateFileTool(worktree).run({"path": "new.txt", "content": "x\n"}).ok


# ─── create_file ─────────────────────────────────────────────────────────────────────
def test_create_file_creates_inside_the_worktree(worktree: Path) -> None:
    result = CreateFileTool(worktree).run({"path": "internal/doc.txt", "content": "hello\n"})
    assert result.ok
    assert (worktree / "internal" / "doc.txt").read_text(encoding="utf-8") == "hello\n"


def test_create_file_refuses_to_overwrite(worktree: Path) -> None:
    result = CreateFileTool(worktree).run({"path": "notes.txt", "content": "clobber"})
    assert not result.ok
    assert "already exists" in (result.error or "")
    assert (worktree / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"


@pytest.mark.parametrize("bad_path", ["../outside.txt", "/etc/owned", "a/../../escape.txt"])
def test_create_file_rejects_paths_outside_the_worktree(worktree: Path, bad_path: str) -> None:
    with pytest.raises(PathValidationError):
        CreateFileTool(worktree).run({"path": bad_path, "content": "x"})


def test_create_file_rejects_git_internals(worktree: Path) -> None:
    with pytest.raises(PathValidationError):
        CreateFileTool(worktree).run({"path": ".git/hooks/pre-commit", "content": "#!/bin/sh\n"})


def test_create_file_enforces_the_size_bound(worktree: Path) -> None:
    with pytest.raises(EditSizeError):
        CreateFileTool(worktree).run({"path": "big.txt", "content": "x" * (MAX_EDIT_BYTES + 1)})


# ─── replace_text ────────────────────────────────────────────────────────────────────
def test_replace_text_replaces_a_unique_match(worktree: Path) -> None:
    result = ReplaceTextTool(worktree).run(
        {"path": "notes.txt", "old_text": "beta", "new_text": "delta"}
    )
    assert result.ok
    assert (worktree / "notes.txt").read_text(encoding="utf-8") == "alpha\ndelta\ngamma\n"


def test_replace_text_reports_a_stale_view_as_an_observation(worktree: Path) -> None:
    result = ReplaceTextTool(worktree).run(
        {"path": "notes.txt", "old_text": "absent", "new_text": "x"}
    )
    assert not result.ok
    assert "not found" in (result.error or "")


def test_replace_text_refuses_an_ambiguous_match(worktree: Path) -> None:
    (worktree / "dup.txt").write_text("same\nsame\n", encoding="utf-8")
    result = ReplaceTextTool(worktree).run({"path": "dup.txt", "old_text": "same", "new_text": "x"})
    assert not result.ok
    assert "ambiguous" in (result.error or "")
    assert (worktree / "dup.txt").read_text(encoding="utf-8") == "same\nsame\n"


def test_replace_text_rejects_paths_outside_the_worktree(worktree: Path) -> None:
    with pytest.raises(PathValidationError):
        ReplaceTextTool(worktree).run({"path": "../notes.txt", "old_text": "a", "new_text": "b"})


def test_replace_text_requires_old_text(worktree: Path) -> None:
    with pytest.raises(ToolError):
        ReplaceTextTool(worktree).run({"path": "notes.txt", "old_text": "", "new_text": "x"})


# ─── delete_file: approval-required ──────────────────────────────────────────────────
def test_delete_file_deletes_only_when_approved(worktree: Path) -> None:
    tool = DeleteFileTool(worktree, ApprovalGate(approve_all))
    result = tool.run({"path": "notes.txt", "reason": "superseded by internal/doc.txt"})
    assert result.ok
    assert not (worktree / "notes.txt").exists()


def test_delete_file_without_approval_deletes_nothing(worktree: Path) -> None:
    gate = ApprovalGate()  # rejects by default
    result = DeleteFileTool(worktree, gate).run({"path": "notes.txt", "reason": "cleanup"})
    assert not result.ok
    assert "rejected" in (result.error or "")
    assert (worktree / "notes.txt").exists()
    # The request itself is on the record: approvals are auditable, not silent.
    assert len(gate.log) == 1
    assert gate.log[0][0].action == "delete_file"


def test_delete_file_rejects_paths_outside_the_worktree(worktree: Path) -> None:
    with pytest.raises(PathValidationError):
        DeleteFileTool(worktree, ApprovalGate(approve_all)).run(
            {"path": "../notes.txt", "reason": "x"}
        )


# ─── inspect_diff ────────────────────────────────────────────────────────────────────
def test_inspect_diff_shows_edits_and_new_files(worktree: Path) -> None:
    ReplaceTextTool(worktree).run({"path": "notes.txt", "old_text": "beta", "new_text": "delta"})
    CreateFileTool(worktree).run({"path": "fresh.txt", "content": "new file\n"})
    result = InspectDiffTool(worktree).run({})
    assert result.ok
    assert "+delta" in result.output
    assert "fresh.txt" in result.output  # intent-to-add makes new files visible


def test_inspect_diff_reports_a_clean_worktree(worktree: Path) -> None:
    result = InspectDiffTool(worktree).run({})
    assert result.ok
    assert result.output == "(no changes)"
