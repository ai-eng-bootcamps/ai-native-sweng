"""Instruction trust, precedence, and conflict detection (Module 4, Lessons 4.2/4.5).

These fail against the scaffolding stubs and pass once the instruction layer is
implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.instructions.precedence import (
    Instruction,
    InstructionCategory,
    TrustLevel,
    detect_conflicts,
    order_by_precedence,
    trust_for_category,
)

pytestmark = pytest.mark.student_impl

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "m04" / "repo"


def _repo_instruction(path: str) -> Instruction:
    return Instruction(
        source_path=path,
        category=InstructionCategory.REPOSITORY,
        trust=TrustLevel.REPOSITORY_TRUSTED,
        text=(FIXTURE_REPO / path).read_text(encoding="utf-8"),
    )


def test_trust_classification_per_category() -> None:
    assert trust_for_category(InstructionCategory.PLATFORM) is TrustLevel.PLATFORM_TRUSTED
    assert trust_for_category(InstructionCategory.WORKER) is TrustLevel.PLATFORM_TRUSTED
    assert trust_for_category(InstructionCategory.TASK) is TrustLevel.HUMAN_APPROVED
    assert trust_for_category(InstructionCategory.REPOSITORY) is TrustLevel.REPOSITORY_TRUSTED


def test_precedence_puts_platform_first_and_repository_last() -> None:
    repo = _repo_instruction("AGENTS.md")
    task = Instruction("task", InstructionCategory.TASK, TrustLevel.HUMAN_APPROVED, "goal")
    platform = Instruction(
        "platform", InstructionCategory.PLATFORM, TrustLevel.PLATFORM_TRUSTED, "rules"
    )
    ordered = order_by_precedence([repo, task, platform])
    assert [i.category for i in ordered] == [
        InstructionCategory.PLATFORM,
        InstructionCategory.TASK,
        InstructionCategory.REPOSITORY,
    ]


def test_fixture_docs_disagree_about_the_hold_lifetime() -> None:
    conflicts = detect_conflicts(
        [_repo_instruction("README.md"), _repo_instruction("docs/architecture.md")],
        ["minutes"],
    )
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.topic == "minutes"
    assert conflict.sources == ("README.md", "docs/architecture.md")
    assert "15" in conflict.claims[0]
    assert "30" in conflict.claims[1]
    # Equal trust: no document wins; the enforced behavior in code settles it.
    assert "unresolved" in conflict.resolution


def test_higher_trust_source_prevails_in_the_resolution() -> None:
    platform = Instruction(
        "platform",
        InstructionCategory.PLATFORM,
        TrustLevel.PLATFORM_TRUSTED,
        "Use at most 6 tool iterations per run.",
    )
    repo = Instruction(
        "AGENTS.md",
        InstructionCategory.REPOSITORY,
        TrustLevel.REPOSITORY_TRUSTED,
        "Use at most 20 tool iterations per run.",
    )
    conflicts = detect_conflicts([platform, repo], ["iterations"])
    assert len(conflicts) == 1
    resolution = conflicts[0].resolution
    assert "platform" in resolution
    assert "takes precedence" in resolution


def test_agreeing_or_single_sources_are_not_conflicts() -> None:
    a = Instruction(
        "a.md", InstructionCategory.REPOSITORY, TrustLevel.REPOSITORY_TRUSTED, "10 days"
    )
    b = Instruction(
        "b.md", InstructionCategory.REPOSITORY, TrustLevel.REPOSITORY_TRUSTED, "10 days"
    )
    assert detect_conflicts([a, b], ["days"]) == ()
    assert detect_conflicts([a], ["days"]) == ()


def test_lines_without_numbers_are_not_claims() -> None:
    a = Instruction(
        "a.md",
        InstructionCategory.REPOSITORY,
        TrustLevel.REPOSITORY_TRUSTED,
        "Holds expire after a short while.",
    )
    b = Instruction(
        "b.md",
        InstructionCategory.REPOSITORY,
        TrustLevel.REPOSITORY_TRUSTED,
        "Holds expire after 30 minutes.",
    )
    assert detect_conflicts([a, b], ["expire"]) == ()
