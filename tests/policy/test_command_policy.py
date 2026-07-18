"""Contract tests for the deterministic command-policy engine (Lesson 3.4).

The engine classifies every argv command into one of six classes and maps each class to
one decision - and it denies by default, follows effect over executable name, and cannot
be talked out of a decision by how a request is phrased. These fail against the
scaffolding stubs and pass once the engine is implemented to the reference behaviour.
"""

import pytest

from anse_harness.policy.commands import (
    CommandClass,
    CommandPolicyEngine,
    PolicyOutcome,
)

pytestmark = pytest.mark.student_impl


@pytest.fixture
def engine() -> CommandPolicyEngine:
    return CommandPolicyEngine()


# ─── one decision per class, drawn from the Lesson 3.4 table ─────────────────────────
def test_read_only_command_is_allowed(engine: CommandPolicyEngine) -> None:
    decision = engine.evaluate(["git", "status", "--porcelain"])
    assert decision.command_class is CommandClass.READ_ONLY
    assert decision.outcome is PolicyOutcome.ALLOW


def test_validation_command_is_allowed(engine: CommandPolicyEngine) -> None:
    decision = engine.evaluate(["go", "test", "./..."])
    assert decision.command_class is CommandClass.VALIDATION
    assert decision.outcome is PolicyOutcome.ALLOW


def test_mutating_command_requires_validation(engine: CommandPolicyEngine) -> None:
    # The formatter's class follows its MODE: -w rewrites files in place.
    decision = engine.evaluate(["gofmt", "-w", "."])
    assert decision.command_class is CommandClass.MUTATING
    assert decision.outcome is PolicyOutcome.ALLOW_WITH_VALIDATION


def test_same_executable_in_check_mode_is_validation(engine: CommandPolicyEngine) -> None:
    # Effect over name: without -w the same executable only reports.
    decision = engine.evaluate(["gofmt", "-l", "."])
    assert decision.command_class is CommandClass.VALIDATION
    assert decision.outcome is PolicyOutcome.ALLOW


def test_destructive_command_requires_approval(engine: CommandPolicyEngine) -> None:
    decision = engine.evaluate(["rm", "-rf", "internal"])
    assert decision.command_class is CommandClass.DESTRUCTIVE
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL


def test_networked_command_requires_approval(engine: CommandPolicyEngine) -> None:
    decision = engine.evaluate(["go", "get", "example.com/pkg"])
    assert decision.command_class is CommandClass.NETWORKED
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL


def test_prohibited_command_is_denied(engine: CommandPolicyEngine) -> None:
    decision = engine.evaluate(["sudo", "rm", "-rf", "/"])
    assert decision.command_class is CommandClass.PROHIBITED
    assert decision.outcome is PolicyOutcome.DENY


# ─── the agent can never merge or publish ────────────────────────────────────────────
def test_git_push_is_denied_outright(engine: CommandPolicyEngine) -> None:
    # Networked AND consequential: the class default (require approval) is overridden
    # to deny - publishing is human-only.
    decision = engine.evaluate(["git", "push", "origin", "main"])
    assert decision.command_class is CommandClass.NETWORKED
    assert decision.outcome is PolicyOutcome.DENY


def test_git_merge_is_denied_outright(engine: CommandPolicyEngine) -> None:
    decision = engine.evaluate(["git", "merge", "anse/run"])
    assert decision.command_class is CommandClass.PROHIBITED
    assert decision.outcome is PolicyOutcome.DENY


# ─── deny by default ─────────────────────────────────────────────────────────────────
def test_unclassified_command_is_denied_by_default(engine: CommandPolicyEngine) -> None:
    decision = engine.evaluate(["python3", "-c", "print('hi')"])
    assert decision.command_class is None
    assert decision.outcome is PolicyOutcome.DENY


def test_malformed_command_is_denied(engine: CommandPolicyEngine) -> None:
    assert engine.evaluate([]).outcome is PolicyOutcome.DENY
    assert engine.evaluate(["git", ""]).outcome is PolicyOutcome.DENY


# ─── determinism: the same request always gets the same decision ─────────────────────
def test_decisions_are_deterministic(engine: CommandPolicyEngine) -> None:
    first = engine.evaluate(["git", "push"])
    second = engine.evaluate(["git", "push"])
    assert first == second
    assert "policy:" in first.render()
