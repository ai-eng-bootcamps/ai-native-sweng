"""Trace-inspector exercises (Lesson 8.6): the six questions over the COMMITTED traces.

Every expectation below is pinned against real committed evidence: the m05 workflow
run, the m06 per-worker set, the m07 escalation set, and the m08 evaluation attempts.
"""

from pathlib import Path

import pytest

from anse_harness.evaluation.inspect import inspect_run

pytestmark = pytest.mark.student_impl

TRACES = Path(__file__).resolve().parents[2] / "traces"


def test_m05_workflow_answers_all_six_questions() -> None:
    inspection = inspect_run([TRACES / "m05" / "workflow_feature_task.jsonl"])
    answers = inspection.six_questions()
    # 1. which context: the investigation packet.
    assert inspection.context_packets >= 1
    # 3. which tools: the recorded investigation/write tool set.
    assert dict(inspection.tool_counts).keys() == {
        "search_text",
        "read_file",
        "replace_text",
        "inspect_diff",
    }
    # 4. where the result changed: artifacts and stage transitions.
    assert len(inspection.artifact_ids) >= 2
    assert len(inspection.transitions) >= 4
    assert inspection.transitions[0][1] == "investigate"
    # 5. why terminated.
    assert inspection.termination == "completed"
    # 6. what it cost (per-call scope only in a single-file run).
    assert round(inspection.per_call_cost_usd, 6) == 0.042180
    assert inspection.per_invocation_cost_usd == 0.0
    assert set(answers) == {
        "which_context",
        "which_worker",
        "which_tools",
        "where_result_changed",
        "why_terminated",
        "what_it_cost_usd",
    }


def test_m06_per_worker_set_identifies_workers_and_reconciles_cost() -> None:
    inspection = inspect_run(sorted((TRACES / "m06").glob("*.jsonl")))
    assert len(inspection.files) == 9
    # 2. which worker acted: eight worker invocations started.
    starts = [pair for pair in inspection.workers if pair[0] == "worker_started"]
    assert len(starts) == 8
    # 6. cost, bucketed by scope: the two buckets agree, and are never summed.
    assert round(inspection.per_call_cost_usd, 6) == 0.10515
    assert round(inspection.per_invocation_cost_usd, 6) == 0.10515


def test_m07_escalation_surfaces_the_termination_reason() -> None:
    inspection = inspect_run(sorted((TRACES / "m07" / "escalation").glob("*.jsonl")))
    assert inspection.termination is not None
    assert "no progress" in inspection.termination
    assert round(inspection.per_call_cost_usd, 6) == 0.100350
    assert round(inspection.per_invocation_cost_usd, 6) == 0.100350


def test_m08_attempt_traces_inspect_cleanly() -> None:
    guided = inspect_run([TRACES / "m08" / "fx-slug-hyphen__cfg-guided__r1.jsonl"])
    assert dict(guided.tool_counts) == {"read_file": 1, "replace_text": 1, "inspect_diff": 1}
    assert guided.termination == "completed"
    assert guided.per_call_cost_usd > 0.0
    terse = inspect_run([TRACES / "m08" / "fx-slug-hyphen__cfg-terse__r1.jsonl"])
    assert dict(terse.tool_counts) == {"replace_text": 1}
    # The configuration difference is visible from the traces alone.
    assert guided.per_call_cost_usd > terse.per_call_cost_usd
    assert guided.event_count > terse.event_count


def test_render_answers_are_human_readable() -> None:
    inspection = inspect_run([TRACES / "m05" / "workflow_feature_task.jsonl"])
    text = inspection.render()
    for prefix in (
        "1. context",
        "2. workers",
        "3. tools",
        "4. result",
        "5. terminated",
        "6. attributed",
    ):
        assert prefix in text
