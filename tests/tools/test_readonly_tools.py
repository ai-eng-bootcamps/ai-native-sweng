"""Contract tests for the Lesson 2.3 read-only tools (list_files, search_text, git status, run).

Each tool is Class 0 (observation only), validates its inputs, and never modifies the
repository. These fail against the scaffolding stubs and pass once the tools are
implemented to the reference behaviour in Module 2, Lesson 2.3.
"""

import subprocess
from pathlib import Path

import pytest

from anse_harness.tools.base import ToolError
from anse_harness.tools.inspect_git_status import InspectGitStatusTool
from anse_harness.tools.list_files import ListFilesTool
from anse_harness.tools.read_file import PathValidationError
from anse_harness.tools.run_read_only_command import RunReadOnlyCommandTool
from anse_harness.tools.search_text import SearchTextTool

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A throwaway Git repository with one untracked file."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    return tmp_path


# ─── contract: every read-only tool is Class 0 with a serializable spec ──────────────
def test_all_read_only_tools_are_class_zero() -> None:
    tools = [
        ListFilesTool(FIXTURE_REPO),
        SearchTextTool(FIXTURE_REPO),
        InspectGitStatusTool(FIXTURE_REPO),
        RunReadOnlyCommandTool(FIXTURE_REPO),
    ]
    for tool in tools:
        assert tool.side_effect_class == 0
        spec = tool.to_spec()
        assert spec.name == tool.name
        assert spec.input_schema["additionalProperties"] is False

    # Smoke-run the two path tools so this also exercises the implementation, not only
    # the supplied contract (both are read-only and touch nothing outside the fixture).
    assert ListFilesTool(FIXTURE_REPO).run({"path": "internal"}).ok
    assert SearchTextTool(FIXTURE_REPO).run({"query": "Status", "path": "internal/booking"}).ok


# ─── list_files ──────────────────────────────────────────────────────────────────────
def test_list_files_lists_sorted_repo_relative_paths() -> None:
    result = ListFilesTool(FIXTURE_REPO).run({"path": "internal"})
    assert result.ok
    lines = result.output.splitlines()
    assert lines == sorted(lines)
    assert "internal/booking/lifecycle.go" in lines
    assert "internal/booking/reservation.go" in lines


@pytest.mark.parametrize("bad_path", ["../../../../etc", "/etc", "internal/../../secrets"])
def test_list_files_rejects_paths_outside_repo(bad_path: str) -> None:
    with pytest.raises(PathValidationError):
        ListFilesTool(FIXTURE_REPO).run({"path": bad_path})


def test_list_files_missing_path_reports_not_ok() -> None:
    result = ListFilesTool(FIXTURE_REPO).run({"path": "internal/does-not-exist"})
    assert not result.ok
    assert result.error is not None


# ─── search_text ─────────────────────────────────────────────────────────────────────
def test_search_text_finds_literal_matches_with_locations() -> None:
    result = SearchTextTool(FIXTURE_REPO).run(
        {"query": "CanTransition", "path": "internal/booking"}
    )
    assert result.ok
    assert "internal/booking/lifecycle.go:" in result.output
    assert "CanTransition" in result.output


def test_search_text_no_match_is_a_benign_observation() -> None:
    result = SearchTextTool(FIXTURE_REPO).run({"query": "zzz_absent_token_zzz"})
    assert result.ok
    assert result.output == "(no matches)"


def test_search_text_requires_a_query() -> None:
    with pytest.raises(ToolError):
        SearchTextTool(FIXTURE_REPO).run({"query": ""})


def test_search_text_rejects_paths_outside_repo() -> None:
    with pytest.raises(PathValidationError):
        SearchTextTool(FIXTURE_REPO).run({"query": "x", "path": "/etc"})


# ─── inspect_git_status ──────────────────────────────────────────────────────────────
def test_inspect_git_status_reports_untracked_file(git_repo: Path) -> None:
    result = InspectGitStatusTool(git_repo).run({})
    assert result.ok
    assert "a.txt" in result.output  # porcelain marks it "?? a.txt"


# ─── run_read_only_command (policy-gated) ────────────────────────────────────────────
def test_run_read_only_command_runs_an_allowlisted_command(git_repo: Path) -> None:
    result = RunReadOnlyCommandTool(git_repo).run({"command": ["git", "status", "--porcelain"]})
    assert result.ok
    assert "a.txt" in result.output


def test_run_read_only_command_denies_a_non_allowlisted_executable() -> None:
    # Denied by policy before anything is executed.
    result = RunReadOnlyCommandTool(FIXTURE_REPO).run({"command": ["rm", "-rf", "/tmp/nope"]})
    assert not result.ok
    assert "policy" in (result.error or "")


def test_run_read_only_command_denies_a_mutating_git_subcommand() -> None:
    result = RunReadOnlyCommandTool(FIXTURE_REPO).run({"command": ["git", "commit", "-m", "x"]})
    assert not result.ok
    assert "policy" in (result.error or "")


def test_run_read_only_command_requires_an_argv_list() -> None:
    with pytest.raises(ToolError):
        RunReadOnlyCommandTool(FIXTURE_REPO).run({"command": "git status"})
