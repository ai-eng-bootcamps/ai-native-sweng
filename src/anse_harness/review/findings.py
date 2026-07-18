"""Review finding schema and reviewer-output parsing (canonical-reference.md section 12).

Review is an evidence-gathering process (arch-ref 40): a finding is a structured claim
about a concrete defect, not prose. Every finding carries its category, severity,
confidence, EVIDENCE (files, lines, tests, reasoning), impact, a recommended action,
and a ``deduplication_key`` - the stable key consolidation uses to collapse duplicates
across reviewers (Lesson 6.6). A finding without evidence must not automatically enter
the fix loop (canonical section 12); the consolidation stage enforces that gate.

Reviewers in this harness report findings inside their final answer, one per line:

    FINDING: {"category": "correctness", "severity": "high", ...}

followed by an explicit conclusion line:

    CONCLUSION: approved | changes_required | insufficient_evidence

``findings_from_text`` and ``conclusion_from_text`` parse that contract
deterministically and fail loudly on malformed finding lines - a reviewer whose output
cannot be validated produces a schema failure, not a silently dropped finding
(arch-ref 44: consolidation validates finding schemas).

SUPPLIED infrastructure: the schema and parsers are consumed as-is; the consolidation
stage (``review/consolidation.py``) and the reviewer runtime (``workers/runner.py``)
are yours to implement in Module 6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

#: Finding categories (canonical section 12).
FINDING_CATEGORIES: tuple[str, ...] = (
    "correctness",
    "security",
    "performance",
    "maintainability",
    "tests",
    "architecture",
)

#: Severity vocabulary (canonical section 12).
FINDING_SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low")

#: Confidence vocabulary (canonical section 12).
FINDING_CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")

#: Reviewer conclusions (canonical section 9.1 output schema).
REVIEW_CONCLUSIONS: tuple[str, ...] = ("approved", "changes_required", "insufficient_evidence")

#: Line prefix a reviewer uses to report one structured finding.
FINDING_LINE_PREFIX = "FINDING: "

#: Line prefix a reviewer uses to state its explicit conclusion.
CONCLUSION_LINE_PREFIX = "CONCLUSION: "


class FindingStatus(StrEnum):
    """The lifecycle of one finding (canonical section 12)."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    FIXED = "fixed"
    UNRESOLVED = "unresolved"
    ESCALATED = "escalated"


class FindingSchemaError(ValueError):
    """A reviewer's reported finding does not satisfy the canonical schema."""


@dataclass(frozen=True)
class FindingEvidence:
    """The evidence one finding rests on (canonical section 12)."""

    files: tuple[str, ...] = ()
    lines: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    reasoning: str = ""

    def is_empty(self) -> bool:
        """True when the finding carries no evidence at all (the fix-loop gate)."""
        return not (self.files or self.lines or self.tests or self.reasoning)

    def to_payload(self) -> dict[str, Any]:
        """Serialize for artifact payloads."""
        return {
            "files": list(self.files),
            "lines": list(self.lines),
            "tests": list(self.tests),
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> FindingEvidence:
        """Deserialize from an artifact payload."""
        return cls(
            files=tuple(str(item) for item in data.get("files", [])),
            lines=tuple(str(item) for item in data.get("lines", [])),
            tests=tuple(str(item) for item in data.get("tests", [])),
            reasoning=str(data.get("reasoning", "")),
        )


@dataclass(frozen=True)
class ReviewFinding:
    """One structured review finding (canonical-reference.md section 12)."""

    finding_id: str
    reviewer_type: str
    category: str
    severity: str
    confidence: str
    summary: str
    evidence: FindingEvidence
    impact: str
    recommended_action: str
    deduplication_key: str
    status: FindingStatus = FindingStatus.PROPOSED

    def with_status(self, status: FindingStatus) -> ReviewFinding:
        """A copy of this finding in a new lifecycle status."""
        return replace(self, status=status)

    def to_payload(self) -> dict[str, Any]:
        """Serialize for artifact payloads."""
        return {
            "finding_id": self.finding_id,
            "reviewer_type": self.reviewer_type,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "summary": self.summary,
            "evidence": self.evidence.to_payload(),
            "impact": self.impact,
            "recommended_action": self.recommended_action,
            "deduplication_key": self.deduplication_key,
            "status": self.status.value,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> ReviewFinding:
        """Deserialize one finding payload."""
        return cls(
            finding_id=str(data["finding_id"]),
            reviewer_type=str(data["reviewer_type"]),
            category=str(data["category"]),
            severity=str(data["severity"]),
            confidence=str(data["confidence"]),
            summary=str(data["summary"]),
            evidence=FindingEvidence.from_payload(dict(data.get("evidence", {}))),
            impact=str(data.get("impact", "")),
            recommended_action=str(data.get("recommended_action", "")),
            deduplication_key=str(data["deduplication_key"]),
            status=FindingStatus(str(data.get("status", "proposed"))),
        )


def _validated_vocabulary(value: str, allowed: tuple[str, ...], field_name: str) -> str:
    if value not in allowed:
        raise FindingSchemaError(
            f"finding {field_name} {value!r} is not in the canonical vocabulary {allowed}"
        )
    return value


def findings_from_text(
    text: str, *, reviewer_type: str, finding_id_prefix: str
) -> tuple[ReviewFinding, ...]:
    """Parse the ``FINDING:`` lines of a reviewer's answer into structured findings.

    Finding ids are assigned deterministically as ``<finding_id_prefix>-<n>`` in
    report order, starting at 1. Every finding starts in status ``proposed``. A line
    that does not parse as JSON, or whose category/severity/confidence fall outside
    the canonical vocabulary, raises ``FindingSchemaError`` - malformed review output
    fails loudly instead of losing findings.
    """
    findings: list[ReviewFinding] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(FINDING_LINE_PREFIX):
            continue
        raw = stripped[len(FINDING_LINE_PREFIX) :]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FindingSchemaError(f"finding line is not valid JSON: {raw!r}") from exc
        if not isinstance(data, dict):
            raise FindingSchemaError(f"finding line must be a JSON object: {raw!r}")
        try:
            category = str(data["category"])
            severity = str(data["severity"])
            confidence = str(data["confidence"])
            summary = str(data["summary"])
            deduplication_key = str(data["deduplication_key"])
        except KeyError as exc:
            raise FindingSchemaError(f"finding is missing required key {exc}: {raw!r}") from exc
        findings.append(
            ReviewFinding(
                finding_id=f"{finding_id_prefix}-{len(findings) + 1}",
                reviewer_type=reviewer_type,
                category=_validated_vocabulary(category, FINDING_CATEGORIES, "category"),
                severity=_validated_vocabulary(severity, FINDING_SEVERITIES, "severity"),
                confidence=_validated_vocabulary(confidence, FINDING_CONFIDENCES, "confidence"),
                summary=summary,
                evidence=FindingEvidence.from_payload(dict(data.get("evidence", {}))),
                impact=str(data.get("impact", "")),
                recommended_action=str(data.get("recommended_action", "")),
                deduplication_key=deduplication_key,
            )
        )
    return tuple(findings)


def conclusion_from_text(text: str) -> str:
    """The reviewer's explicit conclusion, from the last ``CONCLUSION:`` line.

    A missing or unrecognized conclusion is reported as ``insufficient_evidence`` -
    a reviewer that did not state an explicit conclusion has not approved anything
    (arch-ref 40: report uncertainty; the runtime must not infer success).
    """
    conclusion = "insufficient_evidence"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(CONCLUSION_LINE_PREFIX):
            continue
        value = stripped[len(CONCLUSION_LINE_PREFIX) :].strip()
        conclusion = value if value in REVIEW_CONCLUSIONS else "insufficient_evidence"
    return conclusion
