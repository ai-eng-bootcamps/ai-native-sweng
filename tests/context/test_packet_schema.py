"""The context packet schema (canonical-reference.md section 10).

The packet dataclasses and their serialization are SUPPLIED infrastructure, so these
tests run in the default suite: they pin the packet payload to the canonical schema's
exact groups and keys, which is what the ``context_packet_created`` trace event and
every packet consumer rely on.
"""

from anse_harness.context.packet import (
    ContextPacket,
    FileExcerpt,
    FreshnessRecord,
    Omission,
    PacketConflicts,
    PacketConstraints,
    PacketEvidence,
    PacketInstructions,
    PacketProvenance,
    PacketSummary,
)
from anse_harness.instructions.precedence import InstructionConflict, TrustLevel
from anse_harness.repository.symbols import Symbol


def _packet() -> ContextPacket:
    return ContextPacket(
        context_packet_id="cp-t-1-implementer",
        worker_type="implementer",
        task_id="t-1",
        repository_revision="rev-a",
        created_at="2026-01-01T00:00:00+00:00",
        instructions=PacketInstructions(
            platform=("Follow the task.",),
            repository=(FileExcerpt("README.md", "# readme\n"),),
            worker=("Implement the change.",),
            task=("Do the thing.", "It is done."),
        ),
        evidence=PacketEvidence(
            files=(FileExcerpt("internal/booking/hold.go", "package booking\n"),),
            symbols=(Symbol("Hold", "type", "internal/booking/hold.go", 10),),
            tests=(FileExcerpt("internal/booking/hold_test.go", "package booking\n"),),
            architecture_records=(FileExcerpt("docs/architecture.md", "# notes\n"),),
            prior_artifacts=(),
        ),
        constraints=PacketConstraints(
            token_budget=1000, excluded_paths=("vendor",), prohibited_sources=(".git",)
        ),
        provenance=PacketProvenance(
            source_revision="rev-a",
            selection_reasons={"README.md": "repository instruction (readme)"},
            trust_classifications={"README.md": TrustLevel.REPOSITORY_TRUSTED},
            freshness={
                "README.md": FreshnessRecord(
                    "rev-a", "2026-01-01T00:00:00+00:00", "instruction-discovery"
                )
            },
        ),
        conflicts=PacketConflicts(
            items=(InstructionConflict("minutes", ("README.md",), ("15 minutes",), "unresolved"),)
        ),
        summary=PacketSummary(
            token_estimate=42, omissions=(Omission("go.mod", "token_budget", 9),)
        ),
    )


def test_payload_top_level_matches_canonical_schema() -> None:
    payload = _packet().to_payload()
    assert set(payload) == {
        "context_packet_id",
        "worker_type",
        "task_id",
        "repository_revision",
        "created_at",
        "instructions",
        "evidence",
        "constraints",
        "provenance",
        "conflicts",
        "summary",
    }


def test_payload_groups_match_canonical_schema() -> None:
    payload = _packet().to_payload()
    assert set(payload["instructions"]) == {"platform", "repository", "worker", "task"}
    assert set(payload["evidence"]) == {
        "files",
        "symbols",
        "tests",
        "architecture_records",
        "prior_artifacts",
    }
    assert set(payload["constraints"]) == {"token_budget", "excluded_paths", "prohibited_sources"}
    assert set(payload["provenance"]) == {
        "source_revision",
        "selection_reasons",
        "trust_classifications",
        "freshness",
    }
    assert set(payload["conflicts"]) == {"items"}
    assert set(payload["summary"]) == {"token_estimate", "omissions"}


def test_payload_values_are_json_shaped() -> None:
    payload = _packet().to_payload()
    assert payload["instructions"]["repository"] == [{"path": "README.md", "content": "# readme\n"}]
    assert payload["evidence"]["symbols"] == [
        {
            "name": "Hold",
            "kind": "type",
            "file": "internal/booking/hold.go",
            "line": 10,
            "receiver": None,
        }
    ]
    assert payload["provenance"]["trust_classifications"] == {"README.md": "repository-trusted"}
    assert payload["provenance"]["freshness"]["README.md"] == {
        "revision": "rev-a",
        "extracted_at": "2026-01-01T00:00:00+00:00",
        "method": "instruction-discovery",
    }
    assert payload["conflicts"]["items"][0]["sources"] == ["README.md"]
    assert payload["summary"]["omissions"] == [
        {"item": "go.mod", "reason": "token_budget", "tokens": 9}
    ]
