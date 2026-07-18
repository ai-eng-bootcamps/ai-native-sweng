"""Finding consolidation: from raw reviewer output to accepted findings (Lesson 6.6).

Independent reviewers produce findings in parallel and in ignorance of each other -
that independence is the point (Lesson 6.5), and consolidation is where the resulting
redundancy and disagreement are handled EXPLICITLY (arch-ref 44):

* the EVIDENCE GATE: a finding without evidence must not automatically enter the fix
  loop (canonical section 12) - it is rejected, and stays visible as rejected;
* DEDUPLICATION: findings sharing a ``deduplication_key`` and recommending the same
  action collapse to the first reporter's finding; the rest are marked duplicates;
* CONFLICT MARKING: findings sharing a key but recommending DIFFERENT actions are a
  disagreement between reviewers - both are marked for human judgment (escalated),
  because consolidation must identify contradictions, not vote them away;
* everything that survives is ACCEPTED and becomes the fix workers' input.

Consolidation here is fully deterministic - Module 6 deliberately builds the
deterministic tier of arch-ref 44 (model-assisted semantic grouping is discussed in
the lessons, not built). The consolidated review is an artifact: it records every
finding with its final status, so a rejected or duplicate finding remains auditable.

SCAFFOLDING: the consolidated-review contract is supplied; implement
``consolidate_findings`` in Module 6, Lesson 6.6.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from anse_harness.review.findings import ReviewFinding


@dataclass(frozen=True)
class ConsolidatedReview:
    """The consolidation artifact: every finding, grouped by its final status."""

    task_id: str
    iteration: int
    #: Evidence-backed, deduplicated findings, in report order: the fix loop's input.
    accepted: tuple[ReviewFinding, ...]
    #: Findings rejected by the evidence gate (no files, lines, tests, or reasoning).
    rejected: tuple[ReviewFinding, ...]
    #: Findings collapsed into an earlier reporter's finding (same key, same action).
    duplicates: tuple[ReviewFinding, ...]
    #: Contradictory findings (same key, different action): human judgment required.
    conflicting: tuple[ReviewFinding, ...]

    @property
    def has_accepted(self) -> bool:
        """True when at least one finding survived consolidation."""
        return bool(self.accepted)

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the consolidated-review artifact."""
        return {
            "artifact_type": "consolidated_review",
            "task_id": self.task_id,
            "iteration": self.iteration,
            "accepted": [finding.to_payload() for finding in self.accepted],
            "rejected": [finding.to_payload() for finding in self.rejected],
            "duplicates": [finding.to_payload() for finding in self.duplicates],
            "conflicting": [finding.to_payload() for finding in self.conflicting],
        }


def consolidate_findings(
    findings: Sequence[ReviewFinding], *, task_id: str, iteration: int
) -> ConsolidatedReview:
    """Consolidate one review round's findings deterministically (arch-ref 44).

    Processing order is report order (the sequence as given). First the evidence
    gate: findings whose evidence is empty are rejected. Among the evidence-backed
    findings, groups sharing a ``deduplication_key`` are examined: when every
    finding in the group recommends the same action, the first is accepted and the
    rest become duplicates; when recommendations differ, EVERY finding in the group
    is marked conflicting (escalated to human judgment). Findings with a unique key
    are accepted. Statuses are stamped via ``with_status``; input order is
    preserved within each group of the result.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.6: apply the evidence gate (evidence.is_empty -> "
        "status rejected); group the rest by deduplication_key in report order; "
        "same recommended_action -> first accepted, rest duplicates; differing "
        "recommended_action -> all escalated (conflicting); unique keys -> "
        "accepted; return the ConsolidatedReview with statuses stamped."
    )
