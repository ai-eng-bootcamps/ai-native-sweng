"""Context packet schema (canonical-reference.md section 10).

The context packet is the curated, task-specific information supplied to ONE worker
invocation - not the whole repository, not the workflow state, not the conversation
transcript, not permanent memory. Every group below mirrors the canonical schema
exactly: identity, instructions by category, selected evidence, constraints, the
provenance of every selected source, detected conflicts, and a summary carrying the
token estimate and what was omitted to stay inside the budget.

The packet is a frozen value object: once built it does not change, which is what
makes it inspectable BEFORE execution (Module 4, Lesson 4.4) and recordable in the
trace (the ``context_packet_created`` event carries ``to_payload()``).

SUPPLIED infrastructure: the schema and its serialization are consumed as-is; the
builder that fills it is yours to implement in Module 4 (``context/builder.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from anse_harness.instructions.precedence import InstructionConflict, TrustLevel
from anse_harness.repository.symbols import Symbol


@dataclass(frozen=True)
class FileExcerpt:
    """One selected file: its repository-relative POSIX path and its content."""

    path: str
    content: str


@dataclass(frozen=True)
class FreshnessRecord:
    """How one repository-derived item was obtained (architecture-reference 25)."""

    #: Repository revision the item was extracted from.
    revision: str
    #: ISO-8601 extraction time.
    extracted_at: str
    #: Selection method, e.g. "relevance-scoring" or "test-mapping".
    method: str


@dataclass(frozen=True)
class Omission:
    """One item left out of the packet, and why."""

    item: str
    reason: str
    #: Estimated token cost the item would have added.
    tokens: int


@dataclass(frozen=True)
class PacketInstructions:
    """Instructions by category (platform / repository / worker / task).

    ``task`` entries are ordered: the first entry is the task description; every
    following entry is one acceptance criterion.
    """

    platform: tuple[str, ...] = ()
    repository: tuple[FileExcerpt, ...] = ()
    worker: tuple[str, ...] = ()
    task: tuple[str, ...] = ()


@dataclass(frozen=True)
class PacketEvidence:
    """Selected repository evidence, grouped as the canonical schema groups it."""

    files: tuple[FileExcerpt, ...] = ()
    symbols: tuple[Symbol, ...] = ()
    tests: tuple[FileExcerpt, ...] = ()
    architecture_records: tuple[FileExcerpt, ...] = ()
    prior_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PacketConstraints:
    """The limits the builder enforced while selecting."""

    token_budget: int
    excluded_paths: tuple[str, ...] = ()
    prohibited_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class PacketProvenance:
    """Where every selected source came from and why it was selected."""

    source_revision: str
    #: path -> why the builder selected it.
    selection_reasons: dict[str, str] = field(default_factory=dict)
    #: path -> trust level of the source.
    trust_classifications: dict[str, TrustLevel] = field(default_factory=dict)
    #: path -> how and when the item was extracted.
    freshness: dict[str, FreshnessRecord] = field(default_factory=dict)


@dataclass(frozen=True)
class PacketConflicts:
    """Conflicts detected between instruction sources."""

    items: tuple[InstructionConflict, ...] = ()


@dataclass(frozen=True)
class PacketSummary:
    """What the packet costs and what it left out."""

    token_estimate: int
    omissions: tuple[Omission, ...] = ()


@dataclass(frozen=True)
class ContextPacket:
    """One worker invocation's curated context (canonical-reference.md section 10)."""

    context_packet_id: str
    worker_type: str
    task_id: str
    repository_revision: str
    created_at: str
    instructions: PacketInstructions
    evidence: PacketEvidence
    constraints: PacketConstraints
    provenance: PacketProvenance
    conflicts: PacketConflicts
    summary: PacketSummary

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the JSON-shaped payload recorded in the trace."""

        def excerpts(records: tuple[FileExcerpt, ...]) -> list[dict[str, str]]:
            return [{"path": r.path, "content": r.content} for r in records]

        return {
            "context_packet_id": self.context_packet_id,
            "worker_type": self.worker_type,
            "task_id": self.task_id,
            "repository_revision": self.repository_revision,
            "created_at": self.created_at,
            "instructions": {
                "platform": list(self.instructions.platform),
                "repository": excerpts(self.instructions.repository),
                "worker": list(self.instructions.worker),
                "task": list(self.instructions.task),
            },
            "evidence": {
                "files": excerpts(self.evidence.files),
                "symbols": [
                    {
                        "name": s.name,
                        "kind": s.kind,
                        "file": s.file,
                        "line": s.line,
                        "receiver": s.receiver,
                    }
                    for s in self.evidence.symbols
                ],
                "tests": excerpts(self.evidence.tests),
                "architecture_records": excerpts(self.evidence.architecture_records),
                "prior_artifacts": list(self.evidence.prior_artifacts),
            },
            "constraints": {
                "token_budget": self.constraints.token_budget,
                "excluded_paths": list(self.constraints.excluded_paths),
                "prohibited_sources": list(self.constraints.prohibited_sources),
            },
            "provenance": {
                "source_revision": self.provenance.source_revision,
                "selection_reasons": dict(self.provenance.selection_reasons),
                "trust_classifications": {
                    path: str(trust)
                    for path, trust in self.provenance.trust_classifications.items()
                },
                "freshness": {
                    path: {
                        "revision": record.revision,
                        "extracted_at": record.extracted_at,
                        "method": record.method,
                    }
                    for path, record in self.provenance.freshness.items()
                },
            },
            "conflicts": {
                "items": [
                    {
                        "topic": item.topic,
                        "sources": list(item.sources),
                        "claims": list(item.claims),
                        "resolution": item.resolution,
                    }
                    for item in self.conflicts.items
                ],
            },
            "summary": {
                "token_estimate": self.summary.token_estimate,
                "omissions": [
                    {"item": o.item, "reason": o.reason, "tokens": o.tokens}
                    for o in self.summary.omissions
                ],
            },
        }
