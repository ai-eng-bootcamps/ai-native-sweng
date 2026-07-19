"""Metric collection: cost attribution, per-run measures, and matrix summaries (Lesson 8.5).

Two rules keep the numbers in this module honest:

* **Cost is bucketed by budget scope before it is summed.** Committed trace layouts
  carry ``budget_updated`` events in two scopes: worker/engine files record PER-CALL
  costs, and an orchestrator file records PER-INVOCATION AGGREGATES (recognizable by
  the ``worker_invocation_id`` payload field). The two scopes describe the SAME spend
  at different granularities - summing them together double-counts every dollar, and
  measurably doubles the Module 6 trace set's cost. ``attribute_costs`` keeps the
  buckets separate; ``CostAttribution.reconciled`` is the cross-check that the fine
  scope sums to the aggregate scope.

* **Infrastructure runs never enter a pass-rate denominator.** A run the harness could
  not execute or grade says nothing about the task; counting it as a failure would make
  the infrastructure look like the model, and counting it as a pass would be worse.

Summaries also record whether a cell's repetitions were IDENTICAL - in scripted and
replay modes they always are, by construction, and the report layer prints that fact
instead of a fabricated distribution.

SCAFFOLDING: the attribution/summary contracts and the per-trace measures are supplied;
implement ``attribute_costs`` and ``summarize_runs`` in Module 8, Lesson 8.5.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anse_harness.tracing import TraceEvent

if TYPE_CHECKING:
    from anse_harness.evaluation.runner import RunRecord


@dataclass(frozen=True)
class CostAttribution:
    """Attributed model cost, kept in its two budget scopes.

    ``per_call_usd`` sums per-model-call ``budget_updated`` events (worker and engine
    scope); ``per_invocation_usd`` sums per-worker-invocation aggregates (orchestrator
    scope, ``worker_invocation_id`` present in the payload). The event counts make an
    empty scope distinguishable from a zero-cost one.
    """

    per_call_usd: float
    per_invocation_usd: float
    per_call_events: int
    per_invocation_events: int

    def reconciled(self, tolerance: float = 1e-9) -> bool:
        """Whether the fine scope agrees with the aggregate scope.

        True when both scopes are present and their totals match within ``tolerance``,
        and vacuously True when the trace set has no aggregate scope (single-run traces
        have nothing to reconcile against). False means cost attribution is broken and
        no cost figure from this trace set should be reported.
        """
        if self.per_invocation_events == 0:
            return True
        return abs(self.per_call_usd - self.per_invocation_usd) <= tolerance

    def to_payload(self) -> dict[str, Any]:
        """Serialize for reports and artifacts."""
        return {
            "per_call_usd": self.per_call_usd,
            "per_invocation_usd": self.per_invocation_usd,
            "per_call_events": self.per_call_events,
            "per_invocation_events": self.per_invocation_events,
            "reconciled": self.reconciled(),
        }


def attribute_costs(paths: Iterable[Path]) -> CostAttribution:
    """Bucket every ``budget_updated`` event in the trace set by its budget scope.

    An event whose payload carries ``worker_invocation_id`` is an orchestrator-side
    per-invocation aggregate; every other ``budget_updated`` event is a per-call cost.
    The naive alternative - summing all ``cost_usd`` fields across a multi-file set -
    counts the same spend once per scope and roughly DOUBLES the total; this function
    exists so that mistake cannot be made quietly.
    """
    raise NotImplementedError(
        "Module 8, Lesson 8.5: read_trace every path; for each budget_updated event "
        "add payload['cost_usd'] (default 0.0) to the per-invocation bucket when "
        "'worker_invocation_id' is in the payload and to the per-call bucket "
        "otherwise, counting events per bucket; return the CostAttribution."
    )


def trace_duration_seconds(events: Sequence[TraceEvent]) -> float:
    """Elapsed seconds between the first and last event of one trace."""
    if not events:
        return 0.0
    first = datetime.fromisoformat(events[0].timestamp)
    last = datetime.fromisoformat(events[-1].timestamp)
    return (last - first).total_seconds()


def trace_tool_calls(events: Sequence[TraceEvent]) -> int:
    """The number of tool invocations (``tool_requested`` events) in one trace."""
    return sum(1 for event in events if event.event_type == "tool_requested")


@dataclass(frozen=True)
class TaskConfigSummary:
    """Aggregate measures for one (task, configuration) cell of the matrix.

    ``graded_runs`` is the pass-rate DENOMINATOR: runs whose grader delivered a
    verdict. ``pass_rate`` is None when nothing was graded - an unmeasured cell
    reports "unmeasured", never 0% or 100%. ``repetitions_identical`` is True when
    every run of the cell produced the same status, grade, and cost.
    """

    task_id: str
    config_id: str
    mode: str
    runs: int
    infrastructure_runs: int
    graded_runs: int
    passes: int
    pass_rate: float | None
    failure_classes: tuple[tuple[str, int], ...]
    total_cost_usd: float
    mean_cost_usd: float
    mean_duration_seconds: float
    total_tool_calls: int
    repetitions_identical: bool

    def to_payload(self) -> dict[str, Any]:
        """Serialize for reports."""
        return {
            "task_id": self.task_id,
            "config_id": self.config_id,
            "mode": self.mode,
            "runs": self.runs,
            "infrastructure_runs": self.infrastructure_runs,
            "graded_runs": self.graded_runs,
            "passes": self.passes,
            "pass_rate": self.pass_rate,
            "failure_classes": [list(pair) for pair in self.failure_classes],
            "total_cost_usd": self.total_cost_usd,
            "mean_cost_usd": self.mean_cost_usd,
            "mean_duration_seconds": self.mean_duration_seconds,
            "total_tool_calls": self.total_tool_calls,
            "repetitions_identical": self.repetitions_identical,
        }


def summarize_runs(records: Sequence[RunRecord]) -> tuple[TaskConfigSummary, ...]:
    """Reduce run records to one summary per (task, configuration) cell.

    Cells appear in first-seen record order (the matrix order). Within a cell:
    ``infrastructure_runs`` counts records with status ``infrastructure``;
    ``graded_runs`` counts records whose ``graded_pass`` is not None (the denominator);
    ``passes`` counts ``graded_pass`` True; ``pass_rate`` is passes/graded_runs, or
    None when graded_runs is 0; ``failure_classes`` counts each non-None failure class
    in first-seen order; cost/duration/tool-call aggregates cover ALL runs of the cell
    (infrastructure spend is still spend); ``repetitions_identical`` is True when every
    record of the cell has the same (status, graded_pass, cost_usd).
    """
    raise NotImplementedError(
        "Module 8, Lesson 8.5: group records by (task_id, config_id) preserving "
        "first-seen order and compute the cell measures exactly as the contract above "
        "describes, carrying the cell's mode from its records."
    )
