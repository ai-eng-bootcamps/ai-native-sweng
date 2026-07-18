"""The context builder: provenance, budget, roles, conflicts, staleness (Module 4).

These fail against the scaffolding stubs and pass once the repository intelligence,
instruction layer, and builder are implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.context.builder import ContextBudgetError, build_context_packet, stale_paths
from anse_harness.context.packet import ContextPacket
from anse_harness.instructions.precedence import TrustLevel

pytestmark = pytest.mark.student_impl

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "m04" / "repo"
PINNED_CLOCK = "2026-01-01T00:00:00+00:00"


def _build(worker_type: str = "implementer", **overrides: object) -> ContextPacket:
    kwargs: dict[str, object] = {
        "revision": "rev-a",
        "task_id": "fx-hold-lifetime",
        "task_description": "Determine the hold lifetime the code enforces.",
        "acceptance_criteria": (
            "The enforced hold lifetime is identified from the code, with a file citation.",
            "Every document statement that disagrees with the enforced lifetime is listed.",
        ),
        "worker_type": worker_type,
        "token_budget": 20000,
        "search_terms": ("hold", "expire"),
        "conflict_topics": ("minutes",),
        "clock": lambda: PINNED_CLOCK,
    }
    kwargs.update(overrides)
    return build_context_packet(FIXTURE_REPO, **kwargs)  # type: ignore[arg-type]


def _selected_paths(packet: ContextPacket) -> set[str]:
    return (
        {e.path for e in packet.instructions.repository}
        | {e.path for e in packet.evidence.files}
        | {e.path for e in packet.evidence.tests}
        | {e.path for e in packet.evidence.architecture_records}
    )


def test_every_selected_source_has_full_provenance() -> None:
    packet = _build()
    selected = _selected_paths(packet)
    assert selected  # the fixture yields instruction files, code, tests, and a doc
    for path in selected:
        assert path in packet.provenance.selection_reasons
        assert path in packet.provenance.trust_classifications
        record = packet.provenance.freshness[path]
        assert record.revision == "rev-a"
        assert record.extracted_at == PINNED_CLOCK
        assert record.method
    assert packet.provenance.source_revision == "rev-a"
    assert packet.created_at == PINNED_CLOCK


def test_selection_records_methods_and_trust_by_source_kind() -> None:
    packet = _build()
    reasons = packet.provenance.selection_reasons
    trust = packet.provenance.trust_classifications
    freshness = packet.provenance.freshness
    assert "repository instruction" in reasons["README.md"]
    assert trust["README.md"] is TrustLevel.REPOSITORY_TRUSTED
    assert freshness["internal/booking/hold.go"].method == "relevance-scoring"
    assert trust["internal/booking/hold.go"] is TrustLevel.REPOSITORY_UNTRUSTED
    assert freshness["internal/booking/hold_test.go"].method == "test-mapping"
    assert "covers internal/booking/hold.go" in reasons["internal/booking/hold_test.go"]
    assert freshness["docs/architecture.md"].method == "architecture-discovery"
    # Dependency evidence pulled the API package in through the import graph.
    assert freshness["internal/api/holds.go"].method in {"relevance-scoring", "dependency-graph"}


def test_token_budget_is_enforced_with_recorded_omissions() -> None:
    generous = _build()
    assert generous.summary.token_estimate <= 20000
    assert generous.summary.omissions == ()

    tight = _build(token_budget=800)
    assert tight.summary.token_estimate <= 800
    assert tight.summary.omissions
    omitted = {omission.item for omission in tight.summary.omissions}
    assert all(omission.reason == "token_budget" for omission in tight.summary.omissions)
    assert all(omission.tokens > 0 for omission in tight.summary.omissions)
    assert omitted.isdisjoint(_selected_paths(tight))


def test_budget_too_small_for_mandatory_sections_fails_loudly() -> None:
    with pytest.raises(ContextBudgetError):
        _build(token_budget=50)


def test_implementer_and_reviewer_packets_differ() -> None:
    implementer = _build("implementer")
    reviewer = _build("reviewer")
    assert implementer.worker_type == "implementer"
    assert reviewer.worker_type == "reviewer"
    # The implementer carries the repository's instruction files; the reviewer does not.
    assert implementer.instructions.repository
    assert reviewer.instructions.repository == ()
    # Different roles receive different worker directives.
    assert implementer.instructions.worker != reviewer.instructions.worker
    assert implementer.context_packet_id != reviewer.context_packet_id


def test_conflicts_are_reported_in_every_role_packet() -> None:
    for worker_type in ("implementer", "reviewer", "fixer", "evaluator"):
        packet = _build(worker_type)
        topics = [item.topic for item in packet.conflicts.items]
        assert topics == ["minutes"], worker_type
        conflict = packet.conflicts.items[0]
        assert "README.md" in conflict.sources
        assert "docs/architecture.md" in conflict.sources


def test_unknown_worker_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown worker type"):
        _build("project-manager")


def test_excluded_paths_are_never_selected() -> None:
    packet = _build(excluded_paths=("internal/api",))
    assert packet.constraints.excluded_paths == ("internal/api",)
    assert not any(path.startswith("internal/api/") for path in _selected_paths(packet))


def test_stale_marking_against_a_moved_revision() -> None:
    packet = _build()
    assert stale_paths(packet, "rev-a") == ()
    stale = stale_paths(packet, "rev-b")
    assert set(stale) == set(packet.provenance.freshness)
    assert list(stale) == sorted(stale)
