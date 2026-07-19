"""Prompt-injection defense: repository content cannot set policy (Lesson 10.2).

Repository content - AGENTS.md, CONTRIBUTING.md, a ``.rules`` file, README text, issue
bodies, source comments - is EVIDENCE, not authority (architecture-reference 57). Module 4
established instruction precedence (``order_by_precedence``) and numeric-claim conflict
detection (``detect_conflicts``); Module 10 adds the piece Module 4 deliberately leaves
open.

The gap: ``detect_conflicts`` compares trust only AMONG the sources that make a claim, so
when three repository files disagree about autonomy it names one of THEM (for example
AGENTS.md, "autonomy 6, disable sandbox") as the winner - it does not know that all three
sit below platform and task. Taken as-is, the most permissive repository claim wins. That
is exactly the injection a malicious repository wants.

The clamp closes it: for a POLICY topic (autonomy, sandbox, approval, network) no
repository or worker source may set the effective value. Whatever Module 4's
among-sources resolution says, the effective value is the platform/task value, and the
system fails closed. This sits ON TOP of Module 4; it does not replace it.

SCAFFOLDING: the policy-topic set and the ``PolicyIntent`` record are supplied; implement
``resolve_policy_topic`` (the clamp) and ``effective_policy_ignores_untrusted`` in
Module 10, Lesson 10.2.
"""

from __future__ import annotations

from dataclasses import dataclass

from anse_harness.instructions.precedence import InstructionCategory, TrustLevel

#: Topics whose effective value is fixed by platform/task policy and can never be set by
#: repository or worker content (Lesson 10.2; architecture-reference 57-59).
POLICY_TOPICS: frozenset[str] = frozenset({"autonomy", "sandbox", "approval", "network"})

#: The only instruction categories that may set policy: the platform, and the
#: human-approved task. Repository and worker content is evidence, never authority.
AUTHORITATIVE_CATEGORIES: frozenset[InstructionCategory] = frozenset(
    {InstructionCategory.PLATFORM, InstructionCategory.TASK}
)


@dataclass(frozen=True)
class PolicyIntent:
    """A requested policy change parsed out of one instruction source.

    ``kind`` is the change requested (e.g. "disable_sandbox", "push_to_main",
    "raise_autonomy", "exfiltrate"); the category and trust come from the source it was
    parsed from, so the enforcement layer can decide whether that source may set policy.
    """

    kind: str
    source_path: str
    category: InstructionCategory
    trust: TrustLevel


def effective_policy_ignores_untrusted(intents: list[PolicyIntent]) -> list[PolicyIntent]:
    """Keep only the intents that MAY alter policy (platform or task sources).

    Return the subset of ``intents`` whose ``category`` is in ``AUTHORITATIVE_CATEGORIES``.
    Repository- and worker-sourced intents are dropped: they are evidence, not authority,
    so a repository's "disable sandbox" or "push to main" intent never survives to change
    the effective policy.

    Lesson 10.2: untrusted content cannot override platform policy. Implement in Module 10.
    """
    raise NotImplementedError(
        "Module 10, Lesson 10.2: return only the intents whose category is authoritative "
        "(platform or task); drop every repository- and worker-sourced intent."
    )


def resolve_policy_topic(
    topic: str,
    platform_value: str,
    winning_source_category: InstructionCategory,
    winning_value: str,
) -> tuple[str, str]:
    """Clamp a policy topic to the platform value when a non-authoritative source wins.

    This is Module 10's additive injection-defense primitive, closing the gap Module 4's
    ``detect_conflicts`` leaves open. Given the topic, the platform's value for it, and
    the source/value Module 4's among-sources resolution named as the winner:

    * if ``topic`` is a policy topic (in ``POLICY_TOPICS``) AND the winning source's
      category is NOT authoritative (not platform or task), IGNORE the winning value:
      return ``(platform_value, <reason it was clamped, failing closed>)``;
    * otherwise the Module 4 resolution stands: return ``(winning_value, <reason>)``.

    Lesson 10.2: conflicting instructions resolve fail-closed to the platform value, not
    to the most permissive repository claim. Implement in Module 10.
    """
    raise NotImplementedError(
        "Module 10, Lesson 10.2: if topic is a policy topic and the winning source is "
        "not authoritative (platform/task), return the platform value and fail closed; "
        "otherwise return the winning value (the Module 4 resolution stands)."
    )
