"""Replay conformance for the evaluation matrix (Module 8).

The committed ``traces/m08/`` set is a full evaluation artifact: four attempt traces
(2 fixture tasks x 2 prompt configurations x 1 repetition, baseline D via the
UNCHANGED Module 3 write loop over the m05 fixture repository), the run records they
reduce to, and the rendered evaluation report. Conformance proves three things:

1. every attempt REPLAYS through the real ``ReplayAdapter`` and the pinned evaluation
   executor with byte-identical model requests, and the replayed trace matches the
   committed one event for event - after ``normalize_timing_text`` on validation
   payloads, because re-executed ``go test`` prints wall-clock text (``0.006s``) into
   ``validation_completed`` output and ONLY there; model messages never contain it
   (the pinned Module 8 normalization rule);
2. the committed run records are exactly what the committed traces and LIVE re-grading
   reduce to - costs, durations, tool calls, and patch fingerprints from the trace
   bytes; pass/fail verdicts from re-running the committed fixture graders against the
   patches on fresh clones;
3. the committed report regenerates byte-for-byte from the committed records.

The fixture materialization, cost table, report title, and claim checklist are pinned
here and must stay in lockstep with the reference ``cli/run_eval.py`` entry point.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from anse_harness.evaluation.graders import CommandGrader, Grader
from anse_harness.evaluation.inspect import normalize_check_payload
from anse_harness.evaluation.metrics import (
    attribute_costs,
    trace_duration_seconds,
    trace_tool_calls,
)
from anse_harness.evaluation.report import ClaimChecklist, build_evaluation_report
from anse_harness.evaluation.runner import (
    AttemptRequest,
    EvalMatrix,
    EvaluationRunner,
    attempt_trace_filename,
    fresh_clone,
    patch_sha256,
    read_run_records,
    write_task_executor,
)
from anse_harness.models import CostTable, ModelAdapter, ReplayAdapter
from anse_harness.tracing import read_trace

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TRACES = Path(__file__).resolve().parents[2] / "traces" / "m08"

#: Pinned identity and date, so the materialized fixture repository has the same base
#: revision on every machine. Must match the reference trace-generation entry point.
PINNED_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "ANSE Course",
    "GIT_AUTHOR_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_NAME": "ANSE Course",
    "GIT_COMMITTER_EMAIL": "course@ai-eng-bootcamps.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

#: Same non-zero cost table as the recorded set. Must match the reference entry point.
EVAL_COST_TABLE = CostTable(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)

#: Pinned report identity. Must match the reference entry point.
REPORT_TITLE = "Module 8 fixture evaluation: guided vs terse prompt (baseline D)"

#: Pinned canonical-7.7 claim checklist. Must match the reference entry point.
EVAL_CLAIM_CHECKLIST = ClaimChecklist(
    task_set=(
        "fx-slug-hyphen, fx-slug-tests over the m05 practice fixture repository "
        "(pinned baseline revision)"
    ),
    baseline="configuration D (bounded write agent, Module 3 loop) for every cell",
    configuration=(
        "cfg-guided vs cfg-terse (prompt A/B over the same unchanged runtime); "
        "cost table 3/15 USD per Mtok"
    ),
    grader=(
        "fixture hidden graders fx-slug-hyphen and fx-slug-tests "
        "(content-hash versions listed above)"
    ),
    number_of_runs="1 per task and configuration, scripted mode",
    limitations=(
        "scripted mode: model responses are fixed, so run-to-run variance is zero by "
        "construction and live model spend is $0; these runs demonstrate the "
        "evaluation pipeline, not live-model reliability. Live distributions require "
        "funded live runs (pending an owner decision on live evaluation runs)."
    ),
)


def _materialize_fixture_repo(tmp_path: Path) -> Path:
    """Copy the m05 fixture tree and turn it into a pinned one-commit git repository."""
    repo = tmp_path / "source"
    shutil.copytree(FIXTURES / "m05" / "repo", repo)
    env = {**os.environ, **PINNED_COMMIT_ENV}
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "-c", "core.autocrlf=false", "add", "-A"],
        ["git", "commit", "-q", "-m", "Practice fixture baseline"],
    ):
        subprocess.run(args, cwd=repo, env=env, check=True, capture_output=True)
    return repo


def _graders() -> dict[str, Grader]:
    return {
        task_id: CommandGrader(
            task_id,
            FIXTURES / "m08" / "graders" / task_id / f"grade_{task_id.replace('-', '_')}.py",
            interpreter=(sys.executable,),
        )
        for task_id in ("fx-slug-hyphen", "fx-slug-tests")
    }


def _replay_adapter_factory(request: AttemptRequest) -> ModelAdapter:
    trace = TRACES / attempt_trace_filename(
        request.task.task_id, request.configuration.config_id, request.repetition
    )
    return ReplayAdapter(trace, cost_table=EVAL_COST_TABLE)


def _comparable(raw_line: str) -> dict[str, object]:
    """One trace line reduced to its replay-stable form.

    Timestamps and per-call durations are wall clock by nature; validation output
    carries go-test timing text that the pinned normalization makes stable. Every
    other byte - event ids, types, order, payloads including model requests and
    responses - must match exactly.
    """
    event = json.loads(raw_line)
    event.pop("timestamp", None)
    payload = event.get("payload")
    if isinstance(payload, dict):
        payload.pop("duration_ms", None)
        event["payload"] = normalize_check_payload(payload)
    return dict(event)


def test_eval_matrix_replays_and_matches_the_committed_records(tmp_path: Path) -> None:
    source = _materialize_fixture_repo(tmp_path)
    matrix = EvalMatrix.from_file(FIXTURES / "m08" / "eval_matrix.json")
    runner = EvaluationRunner(
        matrix,
        source,
        tmp_path / "work",
        write_task_executor(_replay_adapter_factory),
        _graders(),
    )
    records = runner.run()
    committed = read_run_records(TRACES / "run_records.json")

    assert len(records) == len(committed) == 4
    for replayed, expected in zip(records, committed, strict=True):
        replayed_payload = replayed.to_payload()
        expected_payload = expected.to_payload()
        # Duration is derived from event timestamps, which are wall clock; every
        # other field - outcome, grade, failure class, cost, tool calls, grader
        # version, patch fingerprint, configuration - must reproduce exactly.
        replayed_payload.pop("duration_seconds")
        expected_payload.pop("duration_seconds")
        assert replayed_payload == expected_payload

    # The replayed trace files match the committed ones event for event, after the
    # pinned wall-clock normalization of validation output (and only that).
    for expected in committed:
        committed_lines = (TRACES / expected.trace_ref).read_text(encoding="utf-8").splitlines()
        replayed_lines = (
            (tmp_path / "work" / "traces" / expected.trace_ref)
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert len(replayed_lines) == len(committed_lines)
        for committed_line, replayed_line in zip(committed_lines, replayed_lines, strict=True):
            assert _comparable(replayed_line) == _comparable(committed_line)


def test_committed_records_reduce_from_the_committed_traces(tmp_path: Path) -> None:
    source = _materialize_fixture_repo(tmp_path)
    graders = _graders()
    records = read_run_records(TRACES / "run_records.json")
    assert [(r.task_id, r.config_id) for r in records] == [
        ("fx-slug-hyphen", "cfg-guided"),
        ("fx-slug-hyphen", "cfg-terse"),
        ("fx-slug-tests", "cfg-guided"),
        ("fx-slug-tests", "cfg-terse"),
    ]
    for record in records:
        events = read_trace(TRACES / record.trace_ref)
        # Economic and process measures come from the trace bytes.
        attribution = attribute_costs([TRACES / record.trace_ref])
        assert attribution.per_call_usd == pytest.approx(record.cost_usd)
        assert attribution.per_invocation_events == 0
        assert trace_tool_calls(events) == record.tool_calls
        assert trace_duration_seconds(events) == pytest.approx(record.duration_seconds)
        # The surviving patch travels in the trace's artifact payload.
        patches = [
            event.payload["patch"]
            for event in events
            if event.event_type == "artifact_created" and "patch" in event.payload
        ]
        assert len(patches) == 1
        patch = str(patches[0])
        assert patch_sha256(patch) == record.patch_sha256
        # LIVE re-grading on a fresh clone reproduces the recorded verdict.
        clone = fresh_clone(source, tmp_path / "grade" / record.trace_ref)
        subprocess.run(
            ["git", "apply"],
            cwd=clone,
            input=patch,
            text=True,
            check=True,
            capture_output=True,
        )
        grader = graders[record.grader_id]
        assert grader.version == record.grader_version
        result = grader.grade(clone)
        assert result.infrastructure is False
        assert result.passed is record.graded_pass
        assert record.status == "completed"
        assert record.mode == "scripted"
    # The demonstration beat of the committed matrix: the terse configuration's
    # test-writing attempt passes every VISIBLE check but fails the hidden grader.
    graded = {(r.task_id, r.config_id): r.graded_pass for r in records}
    assert graded[("fx-slug-tests", "cfg-terse")] is False
    assert graded[("fx-slug-tests", "cfg-guided")] is True


def test_committed_report_regenerates_byte_for_byte() -> None:
    records = read_run_records(TRACES / "run_records.json")
    report = build_evaluation_report(
        list(records), title=REPORT_TITLE, claim_checklist=EVAL_CLAIM_CHECKLIST
    )
    committed = (TRACES / "eval_report.md").read_text(encoding="utf-8")
    assert report.render() == committed
