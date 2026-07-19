"""Metric exercises (Lesson 8.5): cost-scope bucketing over the COMMITTED trace sets,
and summaries whose denominators exclude infrastructure.

The Module 6 and 7 committed sets carry the same spend in two budget scopes; summing
both would double-count it. These tests pin the bucketing against the real numbers.
"""

from pathlib import Path

import pytest

from anse_harness.evaluation.metrics import attribute_costs, summarize_runs
from anse_harness.evaluation.runner import RunRecord

pytestmark = pytest.mark.student_impl

TRACES = Path(__file__).resolve().parents[2] / "traces"


def test_m06_costs_bucket_and_reconcile() -> None:
    paths = sorted((TRACES / "m06").glob("*.jsonl"))
    assert len(paths) == 9
    attribution = attribute_costs(paths)
    # Per-worker (per-call) spend and the orchestrator's per-invocation aggregates
    # describe the SAME dollars at two granularities.
    assert round(attribution.per_call_usd, 6) == 0.10515
    assert round(attribution.per_invocation_usd, 6) == 0.10515
    assert attribution.reconciled() is True
    # The naive sum across both scopes is exactly the double-count this API forbids.
    naive = attribution.per_call_usd + attribution.per_invocation_usd
    assert round(naive, 6) == 0.2103


def test_m07_escalation_costs_bucket_and_reconcile() -> None:
    paths = sorted((TRACES / "m07" / "escalation").glob("*.jsonl"))
    assert len(paths) == 9
    attribution = attribute_costs(paths)
    assert round(attribution.per_call_usd, 6) == 0.100350
    assert round(attribution.per_invocation_usd, 6) == 0.100350
    assert attribution.reconciled() is True


def test_single_file_run_has_only_the_per_call_scope() -> None:
    attribution = attribute_costs([TRACES / "m05" / "workflow_feature_task.jsonl"])
    assert round(attribution.per_call_usd, 6) == 0.042180
    assert attribution.per_invocation_events == 0
    assert attribution.reconciled() is True  # nothing to reconcile against


def test_m08_attempt_costs_match_their_run_records() -> None:
    from anse_harness.evaluation.runner import read_run_records

    records = read_run_records(TRACES / "m08" / "run_records.json")
    for record in records:
        attribution = attribute_costs([TRACES / "m08" / record.trace_ref])
        assert attribution.per_call_usd == pytest.approx(record.cost_usd)
        assert attribution.per_invocation_events == 0


def _record(
    task_id: str = "t1",
    config_id: str = "cfg-a",
    repetition: int = 1,
    status: str = "completed",
    graded_pass: bool | None = True,
    failure_class: str | None = None,
    cost_usd: float = 0.01,
) -> RunRecord:
    return RunRecord(
        task_id=task_id,
        config_id=config_id,
        baseline="D",
        repetition=repetition,
        mode="scripted",
        status=status,
        graded_pass=graded_pass,
        failure_class=failure_class,
        grader_id="g",
        grader_version="v1",
        cost_usd=cost_usd,
        duration_seconds=1.0,
        tool_calls=2,
        patch_sha256=None,
        trace_ref="t.jsonl",
    )


def test_infrastructure_runs_never_enter_the_denominator() -> None:
    records = [
        _record(repetition=1, graded_pass=True),
        _record(repetition=2, graded_pass=False, failure_class="implementation failure"),
        _record(
            repetition=3,
            status="infrastructure",
            graded_pass=None,
            failure_class="transient infrastructure failure",
        ),
    ]
    (summary,) = summarize_runs(records)
    assert summary.runs == 3
    assert summary.infrastructure_runs == 1
    assert summary.graded_runs == 2  # the infrastructure run is NOT in the denominator
    assert summary.passes == 1
    assert summary.pass_rate == pytest.approx(0.5)
    assert dict(summary.failure_classes) == {
        "implementation failure": 1,
        "transient infrastructure failure": 1,
    }
    # Spend aggregates cover every run: infrastructure spend is still spend.
    assert summary.total_cost_usd == pytest.approx(0.03)


def test_a_cell_with_nothing_graded_is_unmeasured_not_zero() -> None:
    records = [
        _record(
            status="infrastructure",
            graded_pass=None,
            failure_class="transient infrastructure failure",
        ),
        _record(
            repetition=2,
            status="infrastructure",
            graded_pass=None,
            failure_class="transient infrastructure failure",
        ),
    ]
    (summary,) = summarize_runs(records)
    assert summary.graded_runs == 0
    assert summary.pass_rate is None  # never 0% or 100% without evidence


def test_summaries_group_per_cell_in_matrix_order() -> None:
    records = [
        _record(task_id="t1", config_id="cfg-a"),
        _record(task_id="t1", config_id="cfg-b"),
        _record(task_id="t2", config_id="cfg-a"),
        _record(
            task_id="t2",
            config_id="cfg-b",
            graded_pass=False,
            failure_class="implementation failure",
        ),
    ]
    summaries = summarize_runs(records)
    assert [(s.task_id, s.config_id) for s in summaries] == [
        ("t1", "cfg-a"),
        ("t1", "cfg-b"),
        ("t2", "cfg-a"),
        ("t2", "cfg-b"),
    ]
    assert summaries[3].pass_rate == 0.0


def test_identical_repetitions_are_detected_as_identical() -> None:
    identical = [_record(repetition=n) for n in (1, 2, 3)]
    (summary,) = summarize_runs(identical)
    assert summary.repetitions_identical is True
    differing = [
        _record(repetition=1, cost_usd=0.01),
        _record(repetition=2, cost_usd=0.02),
    ]
    (summary,) = summarize_runs(differing)
    assert summary.repetitions_identical is False
    assert summary.mean_cost_usd == pytest.approx(0.015)
