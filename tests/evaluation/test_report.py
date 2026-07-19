"""Report and comparison exercises (Lessons 8.5-8.7): assembly under the honesty rules.

``build_evaluation_report`` and ``comparison_matrix`` are the student's assembly
steps; the rendering they feed is supplied and structurally honest. These tests build
from the COMMITTED m08 run records where possible, so the exercises run against real
evidence.
"""

import re
from pathlib import Path

import pytest

from anse_harness.evaluation.metrics import summarize_runs
from anse_harness.evaluation.report import (
    ClaimChecklist,
    build_evaluation_report,
    comparison_matrix,
)
from anse_harness.evaluation.runner import EvaluationError, RunRecord, read_run_records

pytestmark = pytest.mark.student_impl

TRACES = Path(__file__).resolve().parents[2] / "traces" / "m08"

CHECKLIST = ClaimChecklist(
    task_set="fixture tasks",
    baseline="configuration D",
    configuration="cfg-guided vs cfg-terse",
    grader="fixture graders",
    number_of_runs="1 per cell",
    limitations="scripted mode; zero variance by construction",
)


def test_report_builds_from_the_committed_records() -> None:
    records = read_run_records(TRACES / "run_records.json")
    report = build_evaluation_report(
        list(records), title="Committed m08 matrix", claim_checklist=CHECKLIST
    )
    assert report.mode == "scripted"
    assert len(report.summaries) == 4  # 2 tasks x 2 configs
    assert report.grader_versions == tuple(
        sorted({(r.grader_id, r.grader_version) for r in records})
    )
    text = report.render()
    assert "Mode: scripted." in text
    assert "identical by construction" in text
    # The one graded failure in the committed matrix appears as a failure class.
    assert "implementation failure x1" in text


def test_report_refuses_empty_and_mixed_mode_records() -> None:
    records = list(read_run_records(TRACES / "run_records.json"))
    with pytest.raises(EvaluationError):
        build_evaluation_report([], title="t", claim_checklist=CHECKLIST)
    mixed = records[:1] + [RunRecord.from_payload({**records[1].to_payload(), "mode": "live"})]
    with pytest.raises(EvaluationError):
        build_evaluation_report(mixed, title="t", claim_checklist=CHECKLIST)


def test_deterministic_mode_report_never_fabricates_variance() -> None:
    records = read_run_records(TRACES / "run_records.json")
    text = build_evaluation_report(list(records), title="t", claim_checklist=CHECKLIST).render()
    # The doctrine sentence is present; no numeric spread is offered anywhere.
    assert "identical by construction" in text
    assert "property of the mode" in text
    assert re.search(r"variance\s*[:=]?\s*\d", text, re.IGNORECASE) is None
    assert "stddev" not in text.lower() and "std dev" not in text.lower()


def test_comparison_matrix_from_the_committed_records() -> None:
    records = read_run_records(TRACES / "run_records.json")
    matrix = comparison_matrix(summarize_runs(records), task_set="fx-slug-hyphen, fx-slug-tests")
    assert matrix.config_ids == ("cfg-guided", "cfg-terse")
    assert matrix.mode == "scripted"
    rows = dict(matrix.rows)
    # cfg-guided passed both tasks; cfg-terse passed one of two.
    assert rows["tasks passed / graded (outcome)"] == ("2/2", "1/2")
    assert rows["pass rate (outcome)"] == ("100%", "50%")
    # Guided spends more (it reads and inspects); the matrix shows the tradeoff.
    guided_cost, terse_cost = (float(v) for v in rows["attributed model cost USD (economic)"])
    assert guided_cost > terse_cost
    text = matrix.render()
    assert "Mode: scripted" in text
    assert "documented negative result" in text


def test_comparison_matrix_refuses_empty_and_mixed_modes() -> None:
    records = read_run_records(TRACES / "run_records.json")
    summaries = summarize_runs(records)
    with pytest.raises(EvaluationError):
        comparison_matrix([], task_set="t")
    live = [RunRecord.from_payload({**r.to_payload(), "mode": "live"}) for r in records[2:]]
    mixed = list(summaries[:1]) + list(summarize_runs(live))
    with pytest.raises(EvaluationError):
        comparison_matrix(mixed, task_set="t")
