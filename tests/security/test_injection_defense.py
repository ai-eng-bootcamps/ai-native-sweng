"""Injection defense: untrusted repository content cannot set policy (Lesson 10.2).

The load-bearing Module 10 regression, run against the hermetic minefield fixture's real
malicious ``AGENTS.md`` / ``CONTRIBUTING.md`` / ``.rules``. Module 4's ``detect_conflicts``
names a REPOSITORY source (AGENTS.md, autonomy 6) the winner of the autonomy conflict -
that is the gap. The Module 10 clamp must hold the effective value at the platform value
regardless. If the clamp regresses (returns the repository claim), these fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anse_harness.instructions.precedence import (
    Instruction,
    InstructionCategory,
    TrustLevel,
    detect_conflicts,
)
from anse_harness.security import (
    POLICY_TOPICS,
    PolicyIntent,
    effective_policy_ignores_untrusted,
    resolve_policy_topic,
)

pytestmark = pytest.mark.student_impl

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "m10" / "minefield-mirror"


def _rule_instructions() -> list[Instruction]:
    """The fixture's three conflicting rule files as Module 4 instruction sources."""
    return [
        Instruction(
            "AGENTS.md",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_TRUSTED,
            (FIXTURE / "AGENTS.md").read_text(encoding="utf-8"),
        ),
        Instruction(
            "CONTRIBUTING.md",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_TRUSTED,
            (FIXTURE / "CONTRIBUTING.md").read_text(encoding="utf-8"),
        ),
        Instruction(
            ".rules",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_UNTRUSTED,
            (FIXTURE / ".rules").read_text(encoding="utf-8"),
        ),
    ]


def test_module4_alone_names_a_repository_source_the_winner() -> None:
    # The gap Module 10 closes: the among-sources resolver names AGENTS.md (a repository
    # source) as the winner of the autonomy conflict - the malicious claim.
    (conflict,) = detect_conflicts(_rule_instructions(), ["autonomy"])
    assert "AGENTS.md" in conflict.resolution


def test_clamp_holds_autonomy_at_the_platform_value_over_the_fixture() -> None:
    # Whatever Module 4 resolved to, the clamp keeps autonomy at the platform value.
    effective, reason = resolve_policy_topic(
        "autonomy",
        platform_value="3",
        winning_source_category=InstructionCategory.REPOSITORY,
        winning_value="6",
    )
    assert effective == "3"  # NOT the repository's "6"
    assert "fail closed" in reason


def test_every_policy_topic_is_clamped_against_a_repository_winner() -> None:
    for topic in POLICY_TOPICS:
        effective, _ = resolve_policy_topic(
            topic,
            platform_value="platform-default",
            winning_source_category=InstructionCategory.REPOSITORY,
            winning_value="attacker-value",
        )
        assert effective == "platform-default"


def test_clamp_leaves_platform_and_task_winners_and_non_policy_topics_alone() -> None:
    # A platform-sourced winner stands (it is authoritative).
    value, _ = resolve_policy_topic("autonomy", "3", InstructionCategory.PLATFORM, "5")
    assert value == "5"
    # A task-sourced winner stands too.
    value, _ = resolve_policy_topic("network", "deny", InstructionCategory.TASK, "allow")
    assert value == "allow"
    # A non-policy topic is not clamped even from a repository source.
    value, _ = resolve_policy_topic("line_length", "100", InstructionCategory.REPOSITORY, "120")
    assert value == "120"


def test_effective_policy_drops_repository_and_worker_intents() -> None:
    intents = [
        PolicyIntent(
            "keep_sandbox", "platform", InstructionCategory.PLATFORM, TrustLevel.PLATFORM_TRUSTED
        ),
        PolicyIntent("count_words", "task", InstructionCategory.TASK, TrustLevel.HUMAN_APPROVED),
        PolicyIntent(
            "disable_sandbox",
            "AGENTS.md",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_TRUSTED,
        ),
        PolicyIntent(
            "push_to_main",
            ".rules",
            InstructionCategory.REPOSITORY,
            TrustLevel.REPOSITORY_UNTRUSTED,
        ),
        PolicyIntent(
            "raise_autonomy",
            "worker",
            InstructionCategory.WORKER,
            TrustLevel.PLATFORM_TRUSTED,
        ),
    ]
    survivors = effective_policy_ignores_untrusted(intents)
    assert {intent.kind for intent in survivors} == {"keep_sandbox", "count_words"}
    assert all(
        intent.category in (InstructionCategory.PLATFORM, InstructionCategory.TASK)
        for intent in survivors
    )
