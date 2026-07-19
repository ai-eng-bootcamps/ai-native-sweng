"""Supplied evaluation scaffolding: contracts that hold before any exercise is solved.

These tests cover the SUPPLIED parts of ``anse_harness.evaluation`` - the manifest and
descriptor schemas, the grader exit-code contract and command grader, the matrix and
run-record round trips, the report rendering honesty rules, the comparison-matrix
adapter over Module 6's report, timing normalization, and the reset-discipline clone
helper - so they run in the default suite and stay green on a fresh clone.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from anse_harness.evaluation.dataset import DatasetDescriptor, DatasetError, TaskManifest
from anse_harness.evaluation.graders import (
    CommandGrader,
    GraderResult,
    grader_version_hash,
    infrastructure_result,
    result_from_exit_code,
)
from anse_harness.evaluation.inspect import (
    filter_events,
    normalize_check_payload,
    normalize_timing_text,
)
from anse_harness.evaluation.metrics import (
    CostAttribution,
    TaskConfigSummary,
    trace_duration_seconds,
    trace_tool_calls,
)
from anse_harness.evaluation.report import (
    CLAIM_CHECKLIST_FIELDS,
    METRIC_CATEGORIES,
    MODE_LABELS,
    ClaimChecklist,
    EvaluationReport,
    matrix_from_comparison_report,
)
from anse_harness.evaluation.runner import (
    EvalMatrix,
    EvaluationError,
    EvaluationRunner,
    RunRecord,
    attempt_trace_filename,
    eval_run_id,
    fresh_clone,
    read_run_records,
    write_run_records,
)
from anse_harness.tracing import TraceEvent
from anse_harness.workflows.comparison import ComparisonReport, ComparisonSide

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = REPO_ROOT / "datasets" / "manifests"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "m08"
TRACES = REPO_ROOT / "traces" / "m08"


def test_task_manifest_loads_a_real_manifest() -> None:
    manifest = TaskManifest.from_file(MANIFESTS / "bk-005.json")
    assert manifest.task_id == "bk-005"
    assert manifest.partition == "development"
    assert manifest.baseline_configuration == "C"
    assert manifest.hidden_validation == "grader:bk-005"
    # Command-kind entries only; the artifact-kind entry is not a command.
    assert manifest.visible_commands == ("go test ./internal/booking/", "go test ./...")
    assert manifest.raw["category"] == "test-creation"


def test_dataset_descriptor_file_loads_and_validates() -> None:
    descriptor = DatasetDescriptor.from_file(REPO_ROOT / "configs" / "evaluation" / "m08-lab.json")
    assert descriptor.dataset_id == "m08-lab"
    assert descriptor.expected_partition == "development"
    assert descriptor.task_ids == (
        "bk-003",
        "bk-004",
        "bk-005",
        "bk-006",
        "bk-009",
        "bk-010",
    )
    # bk-011 is held-out and deliberately not part of the lab dataset.
    assert "bk-011" not in descriptor.task_ids


def test_dataset_descriptor_rejects_bad_declarations() -> None:
    with pytest.raises(DatasetError):
        DatasetDescriptor("d", "x", ("bk-003", "bk-003"), "development")
    with pytest.raises(DatasetError):
        DatasetDescriptor("d", "x", (), "development")
    with pytest.raises(DatasetError):
        DatasetDescriptor("d", "x", ("bk-003",), "secret")


def test_exit_code_contract() -> None:
    assert result_from_exit_code("g", "v", 0, "").passed is True
    assert result_from_exit_code("g", "v", 1, "").passed is False
    for code in (2, 3, 127, -9):
        result = result_from_exit_code("g", "v", code, "")
        assert result.passed is None
        assert result.infrastructure is True
    infra = infrastructure_result("g", "v", "could not run")
    assert infra.passed is None and infra.exit_code is None and infra.infrastructure


def test_grader_result_round_trip_and_consistency_guard() -> None:
    result = GraderResult("g", "v", False, 1, "output", False)
    assert GraderResult.from_payload(result.to_payload()) == result
    with pytest.raises(ValueError):
        GraderResult("g", "v", None, 1, "", False)
    with pytest.raises(ValueError):
        GraderResult("g", "v", True, 0, "", True)


def test_command_grader_contract_and_versioning(tmp_path: Path) -> None:
    outcomes = {}
    for name, code in (("ok", 0), ("bad", 1), ("usage", 2)):
        script = tmp_path / f"{name}.py"
        script.write_text(f"import sys\nsys.exit({code})\n", encoding="utf-8")
        grader = CommandGrader(name, script, interpreter=(sys.executable,))
        outcomes[name] = grader.grade(tmp_path)
        assert grader.version == grader_version_hash(script.read_bytes())
    assert outcomes["ok"].passed is True
    assert outcomes["bad"].passed is False
    assert outcomes["usage"].infrastructure is True
    # A grader that cannot launch at all is infrastructure, never a grade.
    missing = tmp_path / "gone.py"
    missing.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    grader = CommandGrader("gone", missing, interpreter=(sys.executable,))
    missing.unlink()
    assert grader.grade(tmp_path).infrastructure is True


def test_committed_matrix_file_round_trips() -> None:
    matrix = EvalMatrix.from_file(FIXTURES / "eval_matrix.json")
    assert matrix.matrix_id == "m08-fixture-matrix"
    assert matrix.mode == "scripted"
    assert [t.task_id for t in matrix.tasks] == ["fx-slug-hyphen", "fx-slug-tests"]
    assert [c.config_id for c in matrix.configurations] == ["cfg-guided", "cfg-terse"]
    assert matrix.repetitions == 1
    assert EvalMatrix.from_payload(matrix.to_payload()) == matrix
    # The two configurations differ ONLY in prompt rendering - that is the comparison.
    guided, terse = matrix.configurations
    task = matrix.tasks[0]
    assert terse.render_task(task) == task.description
    assert guided.render_task(task).startswith(task.description)
    assert "Guidance:" in guided.render_task(task)


def test_matrix_validation() -> None:
    matrix = EvalMatrix.from_file(FIXTURES / "eval_matrix.json")
    with pytest.raises(EvaluationError):
        EvalMatrix("m", "psychic", matrix.tasks, matrix.configurations, 1)
    with pytest.raises(EvaluationError):
        EvalMatrix("m", "scripted", matrix.tasks, matrix.configurations, 0)
    with pytest.raises(EvaluationError):
        EvalMatrix("m", "scripted", (), matrix.configurations, 1)


def test_runner_requires_a_grader_per_task(tmp_path: Path) -> None:
    matrix = EvalMatrix.from_file(FIXTURES / "eval_matrix.json")
    with pytest.raises(EvaluationError):
        EvaluationRunner(matrix, tmp_path, tmp_path, lambda request: None, {})  # type: ignore[arg-type,return-value]


def test_run_identifiers_are_pinned() -> None:
    assert attempt_trace_filename("t", "c", 2) == "t__c__r2.jsonl"
    assert eval_run_id("t", "c", 2) == "run-eval-t-c-r2"


def test_committed_run_records_load_and_round_trip(tmp_path: Path) -> None:
    records = read_run_records(TRACES / "run_records.json")
    assert len(records) == 4
    for record in records:
        assert record.mode == "scripted"
        assert record.config_id in ("cfg-guided", "cfg-terse")
        assert record.baseline == "D"
        assert record.grader_version
        assert record.trace_ref == attempt_trace_filename(
            record.task_id, record.config_id, record.repetition
        )
        assert (TRACES / record.trace_ref).is_file()
        assert RunRecord.from_payload(record.to_payload()) == record
    write_run_records(records, tmp_path / "rr.json")
    assert read_run_records(tmp_path / "rr.json") == records


def test_fresh_clone_replaces_poisoned_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("baseline\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@invalid",
    }
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "baseline"],
    ):
        subprocess.run(args, cwd=source, env=env, check=True, capture_output=True)
    dest = tmp_path / "clone"
    fresh_clone(source, dest)
    assert (dest / "file.txt").read_text(encoding="utf-8") == "baseline\n"
    (dest / "poison.txt").write_text("stale state\n", encoding="utf-8")
    fresh_clone(source, dest)
    assert not (dest / "poison.txt").exists()
    with pytest.raises(EvaluationError):
        fresh_clone(tmp_path / "nowhere", dest)


def test_vocabulary_constants() -> None:
    assert METRIC_CATEGORIES == ("outcome", "process", "safety", "economic", "human-impact")
    assert set(("scripted", "replay", "live", "live-recorded", "illustrative")) == set(MODE_LABELS)
    assert CLAIM_CHECKLIST_FIELDS == (
        "task_set",
        "baseline",
        "configuration",
        "grader",
        "number_of_runs",
        "limitations",
    )


def test_claim_checklist_requires_every_answer() -> None:
    checklist = ClaimChecklist("t", "b", "c", "g", "n", "l")
    rendered = checklist.render()
    for line in (
        "Task set",
        "Baseline",
        "Configuration",
        "Grader",
        "Number of runs",
        "Limitations",
    ):
        assert line in rendered
    with pytest.raises(EvaluationError):
        ClaimChecklist("t", "b", "c", "g", "n", "  ")


def _summary(**overrides: object) -> TaskConfigSummary:
    base: dict[str, object] = {
        "task_id": "t1",
        "config_id": "cfg-a",
        "mode": "scripted",
        "runs": 3,
        "infrastructure_runs": 0,
        "graded_runs": 3,
        "passes": 3,
        "pass_rate": 1.0,
        "failure_classes": (),
        "total_cost_usd": 0.03,
        "mean_cost_usd": 0.01,
        "mean_duration_seconds": 0.5,
        "total_tool_calls": 6,
        "repetitions_identical": True,
    }
    base.update(overrides)
    return TaskConfigSummary(**base)  # type: ignore[arg-type]


def test_report_render_carries_the_honesty_structure() -> None:
    report = EvaluationReport(
        title="Test report",
        mode="scripted",
        summaries=(
            _summary(),
            _summary(
                config_id="cfg-b", passes=0, pass_rate=None, graded_runs=0, infrastructure_runs=3
            ),
        ),
        grader_versions=(("grader:t1", "abc123def456"),),
        claim_checklist=ClaimChecklist("t", "b", "c", "g", "n", "l"),
    )
    text = report.render()
    # Mode label and the deterministic-mode doctrine sentence.
    assert "Mode: scripted." in text
    assert "identical by construction" in text
    # Category labels on the metric columns.
    for label in ("(outcome)", "(economic)", "(process)"):
        assert label in text
    # No fabricated distribution: an unmeasured cell says so.
    assert "unmeasured" in text
    # Infrastructure exclusion is stated, and the grader version is listed.
    assert "never counted as task failures" in text
    assert "grader:t1 @ abc123def456" in text
    assert "Claim checklist (canonical 7.7)" in text
    with pytest.raises(EvaluationError):
        EvaluationReport("t", "vibes", (), (), ClaimChecklist("t", "b", "c", "g", "n", "l"))


def test_comparison_matrix_adapts_the_module6_report() -> None:
    single = ComparisonSide("single-worker", "completed", "completed", 0.04, 1.0, 2, 0, 0, True)
    multi = ComparisonSide("multi-worker", "completed", "completed", 0.10, 2.0, 8, 2, 1, True)
    matrix = matrix_from_comparison_report(
        ComparisonReport(task_id="fx-tag-style", single=single, multi=multi)
    )
    assert matrix.config_ids == ("single-worker", "multi-worker")
    text = matrix.render()
    assert "Configuration comparison: fx-tag-style" in text
    assert "monetary cost USD (economic)" in text
    assert "0.040000" in text and "0.100000" in text
    # Conclusion-free by design, like its Module 6 ancestor.
    assert "documented negative result" in text


def test_timing_normalization() -> None:
    assert normalize_timing_text("ok  example/pkg\t0.006s") == normalize_timing_text(
        "ok  example/pkg\t0.005s"
    )
    assert normalize_timing_text("--- PASS: TestX (0.00s)") == "--- PASS: TestX (_TIME_s)"
    assert normalize_timing_text("no timing here") == "no timing here"
    checks = [{"name": "go-test", "output": "ok pkg 0.012s", "ok": True}]
    normalized = normalize_check_payload({"ok": True, "checks": checks})
    assert normalized["checks"][0]["output"] == "ok pkg _TIME_s"
    assert checks[0]["output"] == "ok pkg 0.012s"  # original untouched


def test_cost_attribution_reconciliation_logic() -> None:
    both = CostAttribution(0.1, 0.1, 10, 2)
    assert both.reconciled() is True
    broken = CostAttribution(0.1, 0.2, 10, 2)
    assert broken.reconciled() is False
    single_scope = CostAttribution(0.05, 0.0, 5, 0)
    assert single_scope.reconciled() is True  # nothing to reconcile against


def test_filter_events_and_trace_measures() -> None:
    events = [
        TraceEvent(
            "r1", "w", "models", "model_requested", "ok", {}, timestamp="2026-01-01T00:00:00+00:00"
        ),
        TraceEvent(
            "r1",
            "w",
            "runtime",
            "tool_requested",
            "ok",
            {"tool": "read_file"},
            timestamp="2026-01-01T00:00:01+00:00",
        ),
        TraceEvent(
            "r2",
            "w",
            "runtime",
            "tool_requested",
            "ok",
            {"tool": "read_file"},
            timestamp="2026-01-01T00:00:02+00:00",
        ),
    ]
    assert len(filter_events(events, event_type="tool_requested")) == 2
    assert len(filter_events(events, event_type="tool_requested", run_id="r1")) == 1
    assert len(filter_events(events, component="models")) == 1
    assert trace_tool_calls(events) == 2
    assert trace_duration_seconds(events) == 2.0
    assert trace_duration_seconds([]) == 0.0


def test_committed_report_states_its_mode_and_checklist() -> None:
    text = (TRACES / "eval_report.md").read_text(encoding="utf-8")
    assert "Mode: scripted." in text
    assert "identical by construction" in text
    assert "Claim checklist (canonical 7.7)" in text
    assert "pending an owner decision on live evaluation runs" in text
    data = json.loads((TRACES / "run_records.json").read_text(encoding="utf-8"))
    assert len(data["records"]) == 4
