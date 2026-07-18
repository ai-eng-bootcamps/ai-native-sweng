"""Deterministic command-policy engine (spec 7.6; Module 3, Lesson 3.4).

Command execution is the broadest capability the harness exposes, so every requested
command is classified into one of six classes - read-only, validation, mutating,
destructive, networked, prohibited - and each class carries a single default decision:
allow, allow-with-validation, require-approval, or deny. The decision is made HERE, in a
deterministic component outside the model: the model may request any command it likes,
but nothing executes because a string asked for it (Lesson 3.4: the model proposes, the
policy engine disposes).

Two properties are load-bearing:

* **Deny by default.** A command no rule classifies is denied. An allowlist that falls
  through to "allow" is not a safety control.
* **Effect over name.** Rules match mode and arguments, not just the executable, because
  the same tool can act in different classes by flag (a formatter in check mode is
  validation; the same formatter rewriting files in place is mutating). Rule order
  resolves ambiguity toward the more restrictive class: put the restrictive rule first.

SCAFFOLDING: the class and decision vocabulary, the rule catalogue, and the data
contracts are supplied; implement ``CommandRule.matches`` and
``CommandPolicyEngine.evaluate`` in Module 3, Lesson 3.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommandClass(StrEnum):
    """The six command classes of Lesson 3.4, ordered by escalating consequence."""

    READ_ONLY = "read_only"
    VALIDATION = "validation"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"
    NETWORKED = "networked"
    PROHIBITED = "prohibited"


class PolicyOutcome(StrEnum):
    """The four policy decisions a command class maps to."""

    ALLOW = "allow"
    ALLOW_WITH_VALIDATION = "allow_with_validation"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


#: Default decision per command class (Lesson 3.4: the decision escalates with the class).
CLASS_OUTCOMES: dict[CommandClass, PolicyOutcome] = {
    CommandClass.READ_ONLY: PolicyOutcome.ALLOW,
    CommandClass.VALIDATION: PolicyOutcome.ALLOW,
    CommandClass.MUTATING: PolicyOutcome.ALLOW_WITH_VALIDATION,
    CommandClass.DESTRUCTIVE: PolicyOutcome.REQUIRE_APPROVAL,
    CommandClass.NETWORKED: PolicyOutcome.REQUIRE_APPROVAL,
    CommandClass.PROHIBITED: PolicyOutcome.DENY,
}


@dataclass(frozen=True)
class PolicyDecision:
    """The result of evaluating one command: its class, the decision, and the reason."""

    command: tuple[str, ...]
    command_class: CommandClass | None
    outcome: PolicyOutcome
    reason: str

    def render(self) -> str:
        """One-line, model-readable form of the decision (recorded in the trace)."""
        cls = self.command_class.value if self.command_class is not None else "unclassified"
        return f"policy: {self.outcome.value} ({cls}): {self.reason}"


@dataclass(frozen=True)
class CommandRule:
    """One classification rule, matched against an argv command.

    A rule matches when the executable equals ``executable``, the first argument equals
    ``subcommand`` (when set), and every flag in ``with_flags`` (when set) is present
    among the arguments. First matching rule wins, so restrictive rules must be listed
    before permissive ones for the same executable (Lesson 3.4: ambiguity resolves toward
    the more restrictive class).
    """

    executable: str
    command_class: CommandClass
    subcommand: str | None = None
    with_flags: tuple[str, ...] = ()
    #: Overrides the class default (e.g. a networked action that is consequential is
    #: denied outright rather than routed to approval).
    outcome: PolicyOutcome | None = None
    reason: str = ""

    def matches(self, command: list[str]) -> bool:
        """Report whether this rule classifies ``command``."""
        raise NotImplementedError(
            "Module 3, Lesson 3.4: match the executable (command[0]), the subcommand "
            "(command[1]) when this rule sets one, and require every flag in with_flags "
            "to appear among the arguments."
        )


#: Default rules for the course targets (Go repositories operated on through git).
#: Order matters: for one executable the more restrictive rule comes first.
DEFAULT_RULES: tuple[CommandRule, ...] = (
    # Finalizing or publishing a change is never the agent's call: merging bypasses the
    # approval boundary, pushing is an external consequential action (Lesson 3.4).
    CommandRule(
        "git",
        CommandClass.PROHIBITED,
        "merge",
        reason="merging finalizes a change past the approval boundary",
    ),
    CommandRule(
        "git",
        CommandClass.PROHIBITED,
        "rebase",
        reason="rewriting history bypasses the approval boundary",
    ),
    CommandRule(
        "git",
        CommandClass.NETWORKED,
        "push",
        outcome=PolicyOutcome.DENY,
        reason="pushing is an external consequential action; publishing is human-only",
    ),
    CommandRule("git", CommandClass.NETWORKED, "fetch", reason="reaches the network"),
    CommandRule(
        "git",
        CommandClass.NETWORKED,
        "pull",
        reason="reaches the network and rewrites the working copy",
    ),
    # Discarding or deleting state is irreversible inside the worktree.
    CommandRule("git", CommandClass.DESTRUCTIVE, "reset", reason="discards local changes"),
    CommandRule("git", CommandClass.DESTRUCTIVE, "clean", reason="deletes untracked files"),
    CommandRule("git", CommandClass.DESTRUCTIVE, "checkout", reason="can discard local changes"),
    CommandRule("git", CommandClass.MUTATING, "add", reason="stages changes inside the worktree"),
    CommandRule(
        "git", CommandClass.MUTATING, "commit", reason="records changes inside the worktree"
    ),
    CommandRule("git", CommandClass.READ_ONLY, "status", reason="observes working-tree state"),
    CommandRule("git", CommandClass.READ_ONLY, "log", reason="observes history"),
    CommandRule(
        "git",
        CommandClass.VALIDATION,
        "diff",
        with_flags=("--check",),
        reason="whitespace and conflict-marker check",
    ),
    CommandRule("git", CommandClass.READ_ONLY, "diff", reason="observes changes"),
    CommandRule("git", CommandClass.READ_ONLY, "show", reason="observes objects"),
    CommandRule("git", CommandClass.READ_ONLY, "ls-files", reason="observes tracked files"),
    CommandRule("git", CommandClass.READ_ONLY, "rev-parse", reason="observes revisions"),
    CommandRule("git", CommandClass.READ_ONLY, "cat-file", reason="observes objects"),
    CommandRule("git", CommandClass.READ_ONLY, "blame", reason="observes history"),
    # The Go toolchain: fetching dependencies reaches the network; building and testing
    # produce evidence; the formatter's class follows its mode, not its name.
    CommandRule(
        "go", CommandClass.NETWORKED, "get", reason="installs dependencies from the network"
    ),
    CommandRule("go", CommandClass.NETWORKED, "install", reason="installs tools from the network"),
    CommandRule(
        "go", CommandClass.NETWORKED, "mod", reason="can rewrite go.mod and reach the network"
    ),
    CommandRule("go", CommandClass.VALIDATION, "build", reason="compiles the project"),
    CommandRule("go", CommandClass.VALIDATION, "vet", reason="static analysis"),
    CommandRule("go", CommandClass.VALIDATION, "test", reason="runs the test suite"),
    CommandRule(
        "gofmt", CommandClass.MUTATING, with_flags=("-w",), reason="rewrites files in place"
    ),
    CommandRule("gofmt", CommandClass.VALIDATION, reason="formatter in check mode"),
    # Deleting files and privilege or network escapes.
    CommandRule("rm", CommandClass.DESTRUCTIVE, reason="deletes files"),
    CommandRule("curl", CommandClass.NETWORKED, reason="reaches the network"),
    CommandRule("wget", CommandClass.NETWORKED, reason="reaches the network"),
    CommandRule("sudo", CommandClass.PROHIBITED, reason="privilege escalation escapes the sandbox"),
    CommandRule("ssh", CommandClass.PROHIBITED, reason="remote execution escapes the sandbox"),
    CommandRule("scp", CommandClass.PROHIBITED, reason="remote transfer escapes the sandbox"),
)


class CommandPolicyEngine:
    """Classifies argv commands and decides whether they may execute (deny by default)."""

    def __init__(self, rules: tuple[CommandRule, ...] = DEFAULT_RULES) -> None:
        self._rules = rules

    def evaluate(self, command: list[str]) -> PolicyDecision:
        """Return the deterministic decision for one argv command.

        The first matching rule decides the class; the outcome is the rule's override or
        the class default. A command no rule matches is denied - deny by default is the
        property that makes this a safety control rather than a suggestion.
        """
        raise NotImplementedError(
            "Module 3, Lesson 3.4: deny a malformed argv list; return the first matching "
            "rule's class with its outcome override or the CLASS_OUTCOMES default; deny "
            "any command no rule matches (deny by default)."
        )
