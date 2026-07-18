"""Finding consolidation: evidence gate, deduplication, conflicts (Lesson 6.6).

Exercises the deterministic consolidation stage (arch-ref 44) and the canonical
section 12 rule that a finding without evidence must not automatically enter the fix
loop. These fail against the scaffolding stubs and pass once ``consolidate_findings``
is implemented to the reference behaviour.
"""

import pytest

from anse_harness.review.consolidation import consolidate_findings
from anse_harness.review.findings import FindingEvidence, FindingStatus, ReviewFinding

pytestmark = pytest.mark.student_impl


def _finding(
    finding_id: str,
    *,
    reviewer_type: str = "correctness_reviewer",
    key: str = "key-1",
    action: str = "use TrimSpace",
    evidence: FindingEvidence | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        finding_id=finding_id,
        reviewer_type=reviewer_type,
        category="correctness",
        severity="high",
        confidence="high",
        summary=f"summary of {finding_id}",
        evidence=(
            evidence
            if evidence is not None
            else FindingEvidence(files=("a.go",), reasoning="observed")
        ),
        impact="impact",
        recommended_action=action,
        deduplication_key=key,
    )


def test_evidence_gate_rejects_unevidenced_findings_from_the_fix_loop() -> None:
    evidenced = _finding("f-1")
    bare = _finding("f-2", key="other", evidence=FindingEvidence())
    consolidated = consolidate_findings([evidenced, bare], task_id="t", iteration=1)
    assert [finding.finding_id for finding in consolidated.accepted] == ["f-1"]
    assert [finding.finding_id for finding in consolidated.rejected] == ["f-2"]
    assert consolidated.rejected[0].status is FindingStatus.REJECTED


def test_duplicates_collapse_to_the_first_reporter() -> None:
    first = _finding("f-1")
    duplicate = _finding("f-2", reviewer_type="maintainability_reviewer")
    consolidated = consolidate_findings([first, duplicate], task_id="t", iteration=1)
    assert [finding.finding_id for finding in consolidated.accepted] == ["f-1"]
    assert consolidated.accepted[0].status is FindingStatus.ACCEPTED
    assert [finding.finding_id for finding in consolidated.duplicates] == ["f-2"]
    assert consolidated.duplicates[0].status is FindingStatus.DUPLICATE


def test_conflicting_recommendations_escalate_every_group_member() -> None:
    one = _finding("f-1", action="use TrimSpace")
    other = _finding("f-2", action="reject padded input instead")
    consolidated = consolidate_findings([one, other], task_id="t", iteration=1)
    assert consolidated.accepted == ()
    assert [finding.finding_id for finding in consolidated.conflicting] == ["f-1", "f-2"]
    assert all(finding.status is FindingStatus.ESCALATED for finding in consolidated.conflicting)


def test_unique_keys_are_accepted_in_report_order() -> None:
    findings = [_finding("f-1", key="k1"), _finding("f-2", key="k2"), _finding("f-3", key="k3")]
    consolidated = consolidate_findings(findings, task_id="t", iteration=2)
    assert [finding.finding_id for finding in consolidated.accepted] == ["f-1", "f-2", "f-3"]
    assert consolidated.iteration == 2
    assert consolidated.has_accepted


def test_no_findings_consolidates_to_an_empty_accepted_set() -> None:
    consolidated = consolidate_findings([], task_id="t", iteration=1)
    assert not consolidated.has_accepted
    assert consolidated.to_payload()["accepted"] == []


def test_consolidated_payload_keeps_every_finding_auditable() -> None:
    findings = [
        _finding("f-1"),
        _finding("f-2"),
        _finding("f-3", key="other", evidence=FindingEvidence()),
    ]
    payload = consolidate_findings(findings, task_id="t", iteration=1).to_payload()
    assert payload["artifact_type"] == "consolidated_review"
    reported = [
        item["finding_id"]
        for group in ("accepted", "rejected", "duplicates", "conflicting")
        for item in payload[group]
    ]
    assert sorted(reported) == ["f-1", "f-2", "f-3"]
