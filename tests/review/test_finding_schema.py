"""Review finding schema and reviewer-output parsing (canonical-reference.md section 12).

The finding dataclasses and the ``FINDING:``/``CONCLUSION:`` parsers are SUPPLIED
infrastructure, so these tests run in the default suite: they pin the payload round
trip, the deterministic finding-id assignment, the loud failure on malformed or
out-of-vocabulary reviewer output (arch-ref 44: consolidation validates finding
schemas), and the conclusion default that never infers approval.
"""

import json

import pytest

from anse_harness.review.findings import (
    FindingEvidence,
    FindingSchemaError,
    FindingStatus,
    ReviewFinding,
    conclusion_from_text,
    findings_from_text,
)


def _finding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "category": "correctness",
        "severity": "high",
        "confidence": "high",
        "summary": "Normalize keeps trailing whitespace.",
        "evidence": {
            "files": ["internal/tags/normalize.go"],
            "lines": ["7"],
            "tests": [],
            "reasoning": "TrimLeft strips leading spaces only.",
        },
        "impact": "Padded tags stay distinct.",
        "recommended_action": "Use strings.TrimSpace.",
        "deduplication_key": "tags-normalize-trailing-whitespace",
    }
    payload.update(overrides)
    return payload


def test_finding_payload_round_trip() -> None:
    finding = ReviewFinding(
        finding_id="finding-reviewer-1-1-1",
        reviewer_type="correctness_reviewer",
        category="correctness",
        severity="high",
        confidence="high",
        summary="s",
        evidence=FindingEvidence(files=("a.go",), reasoning="because"),
        impact="i",
        recommended_action="fix it",
        deduplication_key="key",
        status=FindingStatus.ACCEPTED,
    )
    assert ReviewFinding.from_payload(finding.to_payload()) == finding


def test_findings_from_text_assigns_deterministic_ids_in_report_order() -> None:
    text = (
        "Prose before.\n"
        f"FINDING: {json.dumps(_finding_payload())}\n"
        f"FINDING: {json.dumps(_finding_payload(deduplication_key='other'))}\n"
        "CONCLUSION: changes_required\n"
    )
    findings = findings_from_text(
        text, reviewer_type="correctness_reviewer", finding_id_prefix="finding-reviewer-1-1"
    )
    assert [finding.finding_id for finding in findings] == [
        "finding-reviewer-1-1-1",
        "finding-reviewer-1-1-2",
    ]
    assert all(finding.status is FindingStatus.PROPOSED for finding in findings)
    assert findings[0].reviewer_type == "correctness_reviewer"
    assert findings[0].evidence.files == ("internal/tags/normalize.go",)


def test_findings_from_text_fails_loudly_on_malformed_json() -> None:
    with pytest.raises(FindingSchemaError, match="not valid JSON"):
        findings_from_text(
            "FINDING: {broken", reviewer_type="correctness_reviewer", finding_id_prefix="f"
        )


def test_findings_from_text_fails_loudly_outside_the_canonical_vocabulary() -> None:
    text = f"FINDING: {json.dumps(_finding_payload(severity='catastrophic'))}"
    with pytest.raises(FindingSchemaError, match="severity"):
        findings_from_text(text, reviewer_type="correctness_reviewer", finding_id_prefix="f")


def test_findings_from_text_fails_loudly_on_missing_required_keys() -> None:
    payload = _finding_payload()
    del payload["deduplication_key"]
    with pytest.raises(FindingSchemaError, match="deduplication_key"):
        findings_from_text(
            f"FINDING: {json.dumps(payload)}",
            reviewer_type="correctness_reviewer",
            finding_id_prefix="f",
        )


def test_conclusion_parsing_never_infers_approval() -> None:
    assert conclusion_from_text("CONCLUSION: approved") == "approved"
    assert conclusion_from_text("CONCLUSION: changes_required") == "changes_required"
    assert conclusion_from_text("looks fine to me") == "insufficient_evidence"
    assert conclusion_from_text("CONCLUSION: ship it") == "insufficient_evidence"


def test_evidence_emptiness_is_the_fix_loop_gate_predicate() -> None:
    assert FindingEvidence().is_empty()
    assert not FindingEvidence(reasoning="observed").is_empty()
    assert not FindingEvidence(files=("a",)).is_empty()
