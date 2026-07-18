"""Packet rendering: prompts and the pre-execution inspection report (Module 4).

These fail against the scaffolding stubs and pass once the builder and renders are
implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.context.builder import build_context_packet
from anse_harness.context.packet import ContextPacket
from anse_harness.context.render import (
    CONTEXT_SYSTEM_PREAMBLE,
    render_packet_report,
    render_system_prompt,
    render_user_prompt,
)

pytestmark = pytest.mark.student_impl

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "m04" / "repo"
PINNED_CLOCK = "2026-01-01T00:00:00+00:00"


def _build(worker_type: str = "implementer", token_budget: int = 20000) -> ContextPacket:
    return build_context_packet(
        FIXTURE_REPO,
        revision="rev-a",
        task_id="fx-hold-lifetime",
        task_description="Determine the hold lifetime the code enforces.",
        acceptance_criteria=("The enforced hold lifetime is identified with a file citation.",),
        worker_type=worker_type,
        token_budget=token_budget,
        search_terms=("hold", "expire"),
        conflict_topics=("minutes",),
        clock=lambda: PINNED_CLOCK,
    )


def test_system_prompt_carries_instructions_in_layered_order() -> None:
    packet = _build()
    prompt = render_system_prompt(packet)
    assert prompt.startswith(CONTEXT_SYSTEM_PREAMBLE)
    assert "Worker role: implementer" in prompt
    assert "Repository revision: rev-a" in prompt
    assert "Platform instructions:" in prompt
    assert "--- README.md ---" in prompt
    # Platform instructions appear before any repository instruction content.
    assert prompt.index("Platform instructions:") < prompt.index("--- README.md ---")


def test_user_prompt_carries_task_conflicts_evidence_and_reasons() -> None:
    packet = _build()
    prompt = render_user_prompt(packet)
    assert prompt.startswith("Task fx-hold-lifetime:")
    assert "Acceptance criteria:" in prompt
    assert "Known instruction conflicts:" in prompt
    assert "minutes" in prompt
    assert "--- internal/booking/hold.go (" in prompt
    assert "const HoldTTLMinutes = 30" in prompt
    assert "Relevant tests (revision rev-a):" in prompt


def test_rendering_is_deterministic_for_the_same_packet() -> None:
    a = _build()
    b = _build()
    assert render_system_prompt(a) == render_system_prompt(b)
    assert render_user_prompt(a) == render_user_prompt(b)


def test_omissions_are_visible_in_the_user_prompt() -> None:
    packet = _build(token_budget=800)
    assert packet.summary.omissions
    prompt = render_user_prompt(packet)
    assert "Omitted for the token budget" in prompt
    assert packet.summary.omissions[0].item in prompt


def test_report_makes_the_packet_auditable_before_execution() -> None:
    # The report is produced from the packet alone - no adapter, no loop, nothing has
    # executed yet - and must surface identity, budget, provenance, and conflicts.
    packet = _build()
    report = render_packet_report(packet)
    assert "cp-fx-hold-lifetime-implementer" in report
    assert "rev-a" in report
    assert PINNED_CLOCK in report
    assert f"of {packet.constraints.token_budget} allowed" in report
    assert "Selected sources (provenance):" in report
    assert "trust: repository-untrusted" in report
    assert "trust: repository-trusted" in report
    assert "method relevance-scoring" in report
    assert "Conflicts:" in report


def test_report_shows_what_the_budget_omitted() -> None:
    packet = _build(token_budget=800)
    report = render_packet_report(packet)
    assert "Omissions:" in report
    assert "token_budget" in report
    assert packet.summary.omissions[0].item in report
