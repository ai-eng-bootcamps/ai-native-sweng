"""Instruction categories, trust classification, precedence, and conflict detection.

Instructions come from sources with very different authority (spec 7.2). The harness
distinguishes WHERE an instruction came from (its category) from HOW MUCH it is trusted
(its trust level, architecture-reference section 26). The two axes are related but not
identical: worker directives are harness-authored (platform-trusted) yet rank below the
human-approved task instructions in precedence, because the task defines the goal the
worker directive merely shapes.

The load-bearing rule is that a lower-trust source must never override a higher-trust
instruction: repository content can advise, it cannot rule. Conflict detection makes
disagreements between sources explicit instead of letting the model silently pick one:
when two sources make different numeric claims about the same topic, the conflict is
recorded with both claims and a resolution that names which source (if any) prevails.

SCAFFOLDING: the vocabulary and data contracts below are supplied; implement
``trust_for_category``, ``order_by_precedence``, and ``detect_conflicts`` in Module 4,
Lessons 4.2 and 4.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TrustLevel(StrEnum):
    """Recommended trust levels (architecture-reference section 26)."""

    PLATFORM_TRUSTED = "platform-trusted"
    HUMAN_APPROVED = "human-approved"
    VALIDATED_ARTIFACT = "validated-artifact"
    REPOSITORY_TRUSTED = "repository-trusted"
    REPOSITORY_UNTRUSTED = "repository-untrusted"
    MODEL_GENERATED_UNVALIDATED = "model-generated-unvalidated"
    EXTERNAL_UNTRUSTED = "external-untrusted"


#: Trust levels from strongest to weakest. A source earlier in this tuple outranks
#: every source later in it; a lower-trust source must not override a higher-trust one.
TRUST_ORDER: tuple[TrustLevel, ...] = (
    TrustLevel.PLATFORM_TRUSTED,
    TrustLevel.HUMAN_APPROVED,
    TrustLevel.VALIDATED_ARTIFACT,
    TrustLevel.REPOSITORY_TRUSTED,
    TrustLevel.REPOSITORY_UNTRUSTED,
    TrustLevel.MODEL_GENERATED_UNVALIDATED,
    TrustLevel.EXTERNAL_UNTRUSTED,
)


class InstructionCategory(StrEnum):
    """Where an instruction came from (spec 7.2 instruction categories)."""

    PLATFORM = "platform"
    TASK = "task"
    WORKER = "worker"
    REPOSITORY = "repository"


#: Precedence from strongest to weakest: platform rules bind everything; the
#: human-approved task defines the goal; worker directives shape how the worker
#: pursues it; repository instructions advise and never override the rest.
CATEGORY_PRECEDENCE: tuple[InstructionCategory, ...] = (
    InstructionCategory.PLATFORM,
    InstructionCategory.TASK,
    InstructionCategory.WORKER,
    InstructionCategory.REPOSITORY,
)


@dataclass(frozen=True)
class Instruction:
    """One instruction source: where it came from, how trusted it is, and its text."""

    source_path: str
    category: InstructionCategory
    trust: TrustLevel
    text: str


@dataclass(frozen=True)
class InstructionConflict:
    """Two or more sources disagreeing about the same topic.

    ``sources`` and ``claims`` are parallel: ``claims[i]`` is the disagreeing line
    found in ``sources[i]``. ``resolution`` names the prevailing source when trust
    levels differ, or states that the conflict is unresolved when they do not.
    """

    topic: str
    sources: tuple[str, ...]
    claims: tuple[str, ...]
    resolution: str


def trust_for_category(category: InstructionCategory) -> TrustLevel:
    """Map an instruction category to its trust level.

    Platform and worker instructions are harness-authored (platform-trusted); task
    instructions are human-approved; repository instruction files are
    repository-trusted. Repository content used as evidence (file contents, not
    instruction files) is classified separately as repository-untrusted.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.2: return the trust level for the category - PLATFORM and "
        "WORKER map to PLATFORM_TRUSTED, TASK to HUMAN_APPROVED, REPOSITORY to "
        "REPOSITORY_TRUSTED."
    )


def order_by_precedence(instructions: list[Instruction]) -> tuple[Instruction, ...]:
    """Return the instructions strongest-first, per ``CATEGORY_PRECEDENCE``.

    Ties within a category are broken by ``source_path`` so the order is deterministic.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.2: sort by (CATEGORY_PRECEDENCE index of category, "
        "source_path) and return a tuple."
    )


def detect_conflicts(
    instructions: list[Instruction], topics: list[str]
) -> tuple[InstructionConflict, ...]:
    """Detect numeric disagreements between instruction sources, one topic at a time.

    For each topic keyword: take, per source, the first line that contains the topic
    (case-insensitive) AND at least one number. If two or more sources produced such a
    claim and their number sequences differ, that topic is one conflict. Sources and
    claims are ordered by ``source_path``. The resolution names the highest-trust
    source (per ``TRUST_ORDER``) when trust levels differ; when all claiming sources
    share one trust level, the conflict is unresolved and says so - the enforced
    behavior in code, not any document, settles it.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.5: per topic, collect (source, first matching numeric line, "
        "extracted numbers) per instruction; if at least two sources claim and their "
        "number tuples are not all equal, emit an InstructionConflict ordered by "
        "source_path, with the trust-based resolution described in the docstring."
    )
