"""Contract tests for the validation pipeline (Lesson 3.5: validation gates).

The pipeline runs the target's own checks and produces a structured report; the worker
cannot claim success - the report decides. Checks are themselves policy-governed: a
check whose command the policy does not allow fails without executing. These fail
against the scaffolding stubs and pass once the pipeline is implemented to the
reference behaviour.
"""

import subprocess
from pathlib import Path

import pytest

from anse_harness.policy.commands import CommandPolicyEngine
from anse_harness.validation.pipeline import ValidationCheck, ValidationPipeline

pytestmark = pytest.mark.student_impl


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A throwaway git worktree with one committed file."""
    repo = tmp_path / "worktree"
    repo.mkdir()
    (repo / "app.txt").write_text("content\n", encoding="utf-8")
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "base"],
    ):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)
    return repo


def _pipeline(worktree: Path, checks: list[ValidationCheck]) -> ValidationPipeline:
    return ValidationPipeline(worktree, checks, CommandPolicyEngine())


def test_passing_checks_produce_a_passing_report(worktree: Path) -> None:
    report = _pipeline(
        worktree,
        [
            ValidationCheck("format-check", ("git", "diff", "--check")),
            ValidationCheck("status", ("git", "status", "--porcelain")),
        ],
    ).run()
    assert report.ok
    assert [result.name for result in report.results] == ["format-check", "status"]
    assert all(result.exit_code == 0 for result in report.results)


def test_a_failing_check_fails_the_report(worktree: Path) -> None:
    # 'git show' on a path missing from HEAD exits nonzero: a deterministic failure.
    report = _pipeline(
        worktree,
        [
            ValidationCheck("format-check", ("git", "diff", "--check")),
            ValidationCheck("must-fail", ("git", "show", "HEAD:absent.txt")),
        ],
    ).run()
    assert not report.ok
    failed = report.results[1]
    assert not failed.ok
    assert failed.exit_code not in (0, None)


def test_a_policy_denied_check_fails_without_executing(worktree: Path) -> None:
    # A pipeline that would run any command is the unrestricted shell in disguise.
    marker = worktree / "should-not-exist.txt"
    report = _pipeline(
        worktree,
        [ValidationCheck("evil", ("touch", str(marker)))],
    ).run()
    assert not report.ok
    denied = report.results[0]
    assert denied.exit_code is None
    assert "policy" in denied.output
    assert not marker.exists()  # never executed


def test_report_payload_is_structured_evidence(worktree: Path) -> None:
    report = _pipeline(
        worktree, [ValidationCheck("format-check", ("git", "diff", "--check"))]
    ).run()
    payload = report.to_payload()
    assert payload["ok"] is True
    assert payload["checks"][0]["name"] == "format-check"
    assert payload["checks"][0]["command"] == ["git", "diff", "--check"]
    assert payload["checks"][0]["exit_code"] == 0
