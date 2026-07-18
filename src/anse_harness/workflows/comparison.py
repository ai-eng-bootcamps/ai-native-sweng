"""Single-worker vs multi-worker comparison (Evidence Gate 4 substrate).

Multi-worker execution is an engineering decision, not a default (Lesson 6.1) - and a
decision needs a measurement. The comparison harness runs the SAME task through the
Module 5 single-worker workflow and the Module 6 orchestrator and reduces both runs to
the same measured dimensions: outcome, monetary cost, elapsed time, worker
invocations, and what the review loop surfaced. Evidence Gate 4 asks for at least one
measured advantage OR a clearly documented negative result - "multi-worker was not
justified for this task" is a valid, publishable conclusion, and this report is
deliberately conclusion-free: it states the numbers; the engineering judgment is
yours.

SCAFFOLDING: the report contract and rendering are supplied; implement
``build_comparison_report`` in Module 6 (lab deliverable: the single-worker
comparison report).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anse_harness.workflows.engine import WorkflowResult
from anse_harness.workflows.orchestrator import MultiWorkerResult


def comparison_artifact_id(task_id: str) -> str:
    """Deterministic identifier of the comparison-report artifact."""
    return f"comparison-{task_id}"


@dataclass(frozen=True)
class ComparisonSide:
    """One architecture's measured outcome for the task."""

    architecture: str
    outcome: str
    termination_reason: str | None
    monetary_cost_usd: float
    elapsed_seconds: float
    worker_invocations: int
    review_iterations: int
    accepted_findings: int
    patch_produced: bool

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the comparison-report artifact."""
        return {
            "architecture": self.architecture,
            "outcome": self.outcome,
            "termination_reason": self.termination_reason,
            "monetary_cost_usd": self.monetary_cost_usd,
            "elapsed_seconds": self.elapsed_seconds,
            "worker_invocations": self.worker_invocations,
            "review_iterations": self.review_iterations,
            "accepted_findings": self.accepted_findings,
            "patch_produced": self.patch_produced,
        }


@dataclass(frozen=True)
class ComparisonReport:
    """The two runs side by side, with the deltas that feed Evidence Gate 4."""

    task_id: str
    single: ComparisonSide
    multi: ComparisonSide

    @property
    def cost_delta_usd(self) -> float:
        """Multi-worker cost minus single-worker cost (positive = multi cost more)."""
        return round(self.multi.monetary_cost_usd - self.single.monetary_cost_usd, 10)

    @property
    def worker_delta(self) -> int:
        """Additional worker invocations the multi-worker run spent."""
        return self.multi.worker_invocations - self.single.worker_invocations

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the comparison-report artifact."""
        return {
            "artifact_type": "comparison_report",
            "task_id": self.task_id,
            "single": self.single.to_payload(),
            "multi": self.multi.to_payload(),
            "cost_delta_usd": self.cost_delta_usd,
            "worker_delta": self.worker_delta,
        }

    def render(self) -> str:
        """A deterministic text table of the measured dimensions (no conclusion).

        The conclusion belongs to the engineer: Evidence Gate 4 accepts a measured
        advantage or a documented negative result, and this report supplies the
        measurements for either.
        """
        rows = (
            ("outcome", self.single.outcome, self.multi.outcome),
            (
                "monetary cost (USD)",
                f"{self.single.monetary_cost_usd:.6f}",
                f"{self.multi.monetary_cost_usd:.6f}",
            ),
            (
                "elapsed (s)",
                f"{self.single.elapsed_seconds:.3f}",
                f"{self.multi.elapsed_seconds:.3f}",
            ),
            (
                "worker invocations",
                str(self.single.worker_invocations),
                str(self.multi.worker_invocations),
            ),
            (
                "review iterations",
                str(self.single.review_iterations),
                str(self.multi.review_iterations),
            ),
            (
                "accepted findings",
                str(self.single.accepted_findings),
                str(self.multi.accepted_findings),
            ),
            (
                "patch produced",
                "yes" if self.single.patch_produced else "no",
                "yes" if self.multi.patch_produced else "no",
            ),
        )
        lines = [
            f"Comparison report: {self.task_id}",
            f"{'dimension':<22} {'single-worker':<16} {'multi-worker':<16}",
        ]
        lines.extend(f"{name:<22} {single:<16} {multi:<16}" for name, single, multi in rows)
        lines.append(
            f"cost delta (multi - single): {self.cost_delta_usd:+.6f} USD; "
            f"worker delta: {self.worker_delta:+d}"
        )
        return "\n".join(lines) + "\n"


def build_comparison_report(
    task_id: str, single: WorkflowResult, multi: MultiWorkerResult
) -> ComparisonReport:
    """Reduce one single-worker and one multi-worker run to the comparison report.

    Both sides read the same fields of the same state schema: outcome and
    termination reason from the status block, cost/elapsed/worker count from the
    budgets block. The single-worker side has no review loop by construction, so
    its review iterations and accepted findings are zero - that asymmetry is part
    of the measurement, not noise.
    """
    raise NotImplementedError(
        "Module 6 lab: build both ComparisonSides from the two results' states "
        "(status, budgets, patches; review iterations and final consolidated "
        "accepted findings for the multi side) and return the ComparisonReport."
    )
