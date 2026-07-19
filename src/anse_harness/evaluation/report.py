"""Evaluation reports: category-labeled metrics, claim checklists, and mode honesty.

A report is the artifact an engineering decision gets made from, so its structure
enforces the discipline the numbers need (canonical section 7):

* every metric column carries its MEASUREMENT CATEGORY label - outcome, process,
  safety, economic, human-impact - because metrics from one category never substitute
  for another (7.6: passing tests do not prove maintainability);
* every report states its execution MODE, and every figure inherits it. Scripted and
  replay runs are deterministic: repeated runs are identical BY CONSTRUCTION, so the
  report says exactly that instead of plotting a fabricated distribution. Spread,
  variance, and pass@k exist only for live runs, and figures from recorded live data
  or illustration must be labeled ``live-recorded`` or ``illustrative``;
* every report ends with the canonical 7.7 CLAIM CHECKLIST - task set, baseline,
  configuration, grader, number of runs, limitations - because an evaluation claim
  without those six answers is not checkable;
* infrastructure runs are reported and visibly EXCLUDED from pass-rate denominators.

The configuration-comparison matrix generalizes Module 6's two-sided comparison report
to N configurations; ``matrix_from_comparison_report`` adapts the Module 6 report into
the same renderer, so the Evidence Gate 4 entry point keeps working unchanged. Like its
Module 6 ancestor, the matrix is deliberately conclusion-free: it states measurements;
the engineering judgment is yours.

SCAFFOLDING: the report/matrix contracts and rendering are supplied; implement
``build_evaluation_report`` and ``comparison_matrix`` in Module 8, Lessons 8.5-8.7.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from anse_harness.evaluation.metrics import TaskConfigSummary
from anse_harness.evaluation.runner import EvaluationError, RunRecord
from anse_harness.workflows.comparison import ComparisonReport

#: The five measurement categories of canonical section 7. Every reported metric is
#: labeled with exactly one of them.
METRIC_CATEGORIES: tuple[str, ...] = (
    "outcome",
    "process",
    "safety",
    "economic",
    "human-impact",
)

#: Mode labels a report or figure may carry. The first three are execution modes;
#: ``live-recorded`` marks instructor-recorded live data and ``illustrative`` marks
#: invented example numbers - both must be labeled as such wherever they appear.
MODE_LABELS: tuple[str, ...] = (
    "scripted",
    "replay",
    "live",
    "live-recorded",
    "illustrative",
)

#: The six answers every evaluation claim must identify (canonical 7.7).
CLAIM_CHECKLIST_FIELDS: tuple[str, ...] = (
    "task_set",
    "baseline",
    "configuration",
    "grader",
    "number_of_runs",
    "limitations",
)

#: The deterministic-mode honesty sentence every scripted/replay report carries.
DETERMINISTIC_MODE_NOTE = (
    "Repeated runs in this mode are identical by construction: model responses are "
    "fixed, so re-running reproduces the same result at zero live model spend. The "
    "absence of spread below is a property of the mode, not evidence of reliability; "
    "success-rate variance, flaky rates, and pass@k are properties of live runs only."
)

#: The live-mode counterpart: spread is expected and must be measured, not assumed.
LIVE_MODE_NOTE = (
    "Live runs sample from a model: the same task and configuration produce different "
    "runs, costs, and outcomes. Single-run figures below are point observations, not "
    "distributions."
)


@dataclass(frozen=True)
class ClaimChecklist:
    """The canonical 7.7 claim checklist: six answers, all mandatory, none empty."""

    task_set: str
    baseline: str
    configuration: str
    grader: str
    number_of_runs: str
    limitations: str

    def __post_init__(self) -> None:
        for field_name in CLAIM_CHECKLIST_FIELDS:
            if not getattr(self, field_name).strip():
                raise EvaluationError(f"claim checklist field {field_name!r} is empty")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for report artifacts."""
        return {name: getattr(self, name) for name in CLAIM_CHECKLIST_FIELDS}

    def render(self) -> str:
        """The checklist as markdown bullet lines."""
        lines = [
            f"- Task set: {self.task_set}",
            f"- Baseline: {self.baseline}",
            f"- Configuration: {self.configuration}",
            f"- Grader: {self.grader}",
            f"- Number of runs: {self.number_of_runs}",
            f"- Limitations: {self.limitations}",
        ]
        return "\n".join(lines)


def _percent(rate: float | None) -> str:
    """Render a pass rate; an unmeasured cell says so instead of showing a number."""
    if rate is None:
        return "unmeasured"
    return f"{rate:.0%}"


def _failure_classes(pairs: tuple[tuple[str, int], ...]) -> str:
    """Render a failure-class distribution cell."""
    if not pairs:
        return "-"
    return "; ".join(f"{name} x{count}" for name, count in pairs)


@dataclass(frozen=True)
class EvaluationReport:
    """One evaluation's evidence: summaries, grader identities, mode, and claims."""

    title: str
    mode: str
    summaries: tuple[TaskConfigSummary, ...]
    grader_versions: tuple[tuple[str, str], ...]
    claim_checklist: ClaimChecklist

    def __post_init__(self) -> None:
        if self.mode not in MODE_LABELS:
            raise EvaluationError(f"unknown report mode {self.mode!r}")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for artifacts."""
        return {
            "title": self.title,
            "mode": self.mode,
            "summaries": [summary.to_payload() for summary in self.summaries],
            "grader_versions": [list(pair) for pair in self.grader_versions],
            "claim_checklist": self.claim_checklist.to_payload(),
        }

    def render(self) -> str:
        """The report as deterministic markdown.

        The honesty rules are structural: the mode note is chosen by mode, repetition
        cells state identity instead of spread, every metric column names its
        category, and the claim checklist is always the closing section.
        """
        deterministic = self.mode in ("scripted", "replay")
        lines = [
            f"# {self.title}",
            "",
            f"Mode: {self.mode}. Every figure in this report was produced in this "
            "mode and is labeled with its measurement category (canonical section 7).",
            "",
            DETERMINISTIC_MODE_NOTE if deterministic else LIVE_MODE_NOTE,
            "",
            "## Results by task and configuration",
            "",
            "| task | configuration | mode | runs | repetitions | pass rate (outcome) "
            "| attributed model cost USD (economic) | mean duration s (process) "
            "| tool calls (process) | failure classes (process) "
            "| infrastructure runs (excluded from denominator) |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for cell in self.summaries:
            if deterministic and cell.repetitions_identical:
                repetitions = f"{cell.runs} (identical by construction)"
            elif cell.repetitions_identical:
                repetitions = f"{cell.runs} (identical)"
            else:
                repetitions = f"{cell.runs} (differing)"
            lines.append(
                f"| {cell.task_id} | {cell.config_id} | {cell.mode} | {cell.runs} "
                f"| {repetitions} | {_percent(cell.pass_rate)} "
                f"| {cell.total_cost_usd:.6f} | {cell.mean_duration_seconds:.3f} "
                f"| {cell.total_tool_calls} | {_failure_classes(cell.failure_classes)} "
                f"| {cell.infrastructure_runs} |"
            )
        lines += [
            "",
            "Pass-rate denominators count graded runs only; infrastructure failures "
            "(harness, environment, or grader faults) are shown in their own column "
            "and never counted as task failures.",
            "",
            "## Grader versions",
            "",
        ]
        lines.extend(f"- {grader_id} @ {version}" for grader_id, version in self.grader_versions)
        lines += [
            "",
            "## Claim checklist (canonical 7.7)",
            "",
            self.claim_checklist.render(),
        ]
        return "\n".join(lines) + "\n"


def build_evaluation_report(
    records: Sequence[RunRecord],
    *,
    title: str,
    claim_checklist: ClaimChecklist,
) -> EvaluationReport:
    """Assemble the report artifact from run records.

    All records must share ONE mode - a report mixing modes would need per-figure
    labels this template does not provide, so mixing is refused loudly. Grader
    versions are the unique (grader_id, grader_version) pairs, sorted.
    """
    raise NotImplementedError(
        "Module 8, Lesson 8.5: refuse an empty record set and any mixed-mode record "
        "set (EvaluationError); summarize the records with summarize_runs; collect "
        "the sorted unique (grader_id, grader_version) pairs; return the "
        "EvaluationReport carrying the shared mode."
    )


@dataclass(frozen=True)
class ComparisonMatrix:
    """N configurations side by side over one task set, conclusion-free.

    ``rows`` pair a category-labeled dimension name with one value per configuration,
    in ``config_ids`` order.
    """

    task_set: str
    config_ids: tuple[str, ...]
    rows: tuple[tuple[str, tuple[str, ...]], ...]
    mode: str | None = None

    def __post_init__(self) -> None:
        if self.mode is not None and self.mode not in MODE_LABELS:
            raise EvaluationError(f"unknown matrix mode {self.mode!r}")
        for name, values in self.rows:
            if len(values) != len(self.config_ids):
                raise EvaluationError(
                    f"row {name!r} has {len(values)} values for "
                    f"{len(self.config_ids)} configurations"
                )

    def render(self) -> str:
        """A deterministic text table (no conclusion; the judgment is the engineer's)."""
        width = max(
            (len(name) for name, _ in self.rows),
            default=len("dimension"),
        )
        width = max(width, len("dimension")) + 2
        col = (
            max(
                [len(config_id) for config_id in self.config_ids]
                + [len(value) for _, values in self.rows for value in values]
                + [12]
            )
            + 2
        )
        lines = [f"Configuration comparison: {self.task_set}"]
        if self.mode is not None:
            lines.append(f"Mode: {self.mode}")
        header = f"{'dimension':<{width}}" + "".join(
            f"{config_id:<{col}}" for config_id in self.config_ids
        )
        lines.append(header)
        for name, values in self.rows:
            lines.append(f"{name:<{width}}" + "".join(f"{value:<{col}}" for value in values))
        lines.append(
            "This matrix states measurements; a documented negative result is as "
            "publishable as an advantage."
        )
        return "\n".join(lines) + "\n"


def comparison_matrix(summaries: Sequence[TaskConfigSummary], *, task_set: str) -> ComparisonMatrix:
    """Reduce per-cell summaries to one configuration-comparison matrix.

    Configurations appear in first-seen summary order; each aggregates its cells
    across the task set. Rows (in this order, with these labels): ``tasks passed /
    graded (outcome)`` as ``P/G``, ``pass rate (outcome)`` via the report's percent
    rendering, ``attributed model cost USD (economic)`` as a 6-decimal total,
    ``mean duration s (process)`` as the run-weighted mean over cells (3 decimals),
    ``tool calls (process)`` as a total, and ``infrastructure runs (excluded)`` as a
    total. The matrix mode is the summaries' shared mode (mixed modes are refused).
    """
    raise NotImplementedError(
        "Module 8, Lesson 8.7: group summaries by config_id preserving first-seen "
        "order, refuse an empty or mixed-mode input (EvaluationError), aggregate the "
        "six rows exactly as the contract above describes, and return the "
        "ComparisonMatrix."
    )


def matrix_from_comparison_report(report: ComparisonReport) -> ComparisonMatrix:
    """Adapt Module 6's two-sided comparison report into the N-configuration matrix.

    This keeps the Evidence Gate 4 entry point (``build_comparison_report``) stable:
    its output feeds the same renderer as any N-configuration evaluation, with the
    Module 6 dimensions carrying their measurement-category labels.
    """
    single, multi = report.single, report.multi
    rows: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("outcome (outcome)", (single.outcome, multi.outcome)),
        (
            "monetary cost USD (economic)",
            (f"{single.monetary_cost_usd:.6f}", f"{multi.monetary_cost_usd:.6f}"),
        ),
        (
            "elapsed s (process)",
            (f"{single.elapsed_seconds:.3f}", f"{multi.elapsed_seconds:.3f}"),
        ),
        (
            "worker invocations (process)",
            (str(single.worker_invocations), str(multi.worker_invocations)),
        ),
        (
            "review iterations (process)",
            (str(single.review_iterations), str(multi.review_iterations)),
        ),
        (
            "accepted findings (process)",
            (str(single.accepted_findings), str(multi.accepted_findings)),
        ),
        (
            "patch produced (outcome)",
            (
                "yes" if single.patch_produced else "no",
                "yes" if multi.patch_produced else "no",
            ),
        ),
    )
    return ComparisonMatrix(
        task_set=report.task_id,
        config_ids=(single.architecture, multi.architecture),
        rows=rows,
    )
