"""Loop termination under limits: the iteration cap and the cost budget (Lesson 2.4).

The iteration cap stops a runaway loop as ``limit_exceeded``; the cost budget stops it as
``escalated`` (a hand-off to a human, not a silent stop). These fail against the
scaffolding stubs and pass once ``ExecutionState`` and the loop are implemented to the
reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.models import (
    CostTable,
    ModelResponse,
    ScriptedAdapter,
    ScriptStep,
    ToolCall,
    Usage,
)
from anse_harness.runtime.loop import run_investigation
from anse_harness.state.state import ExecutionState, RunStatus
from anse_harness.tools.base import ToolRegistry
from anse_harness.tools.read_file import ReadFileTool

pytestmark = pytest.mark.student_impl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"
TASK = (FIXTURES / "task.txt").read_text(encoding="utf-8").strip()
TARGET = "internal/booking/reservation.go"


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(FIXTURE_REPO))
    return registry


def _always_reads(cost_table: CostTable | None = None) -> ScriptedAdapter:
    return ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text="reading again",
                    tool_calls=[
                        ToolCall(id="call-1", name="read_file", arguments={"path": TARGET})
                    ],
                    usage=Usage(input_tokens=1000, output_tokens=1000),
                    stop_reason="tool_use",
                )
            )
        ],
        cost_table=cost_table,
    )


# ─── ExecutionState.charge unit behaviour ────────────────────────────────────────────
def test_charge_escalates_when_cost_budget_exhausted() -> None:
    state = ExecutionState(max_iterations=6, max_cost_usd=0.001)
    assert state.charge(0.0004) is False  # under budget
    under_budget: RunStatus = state.status
    assert under_budget is RunStatus.RUNNING
    assert state.charge(0.0007) is True  # crosses the budget
    exhausted: RunStatus = state.status
    assert exhausted is RunStatus.ESCALATED
    assert state.cost_usd == pytest.approx(0.0011)


def test_charge_without_a_budget_never_escalates() -> None:
    state = ExecutionState(max_iterations=6)
    assert state.charge(999.0) is False
    status: RunStatus = state.status
    assert status is RunStatus.RUNNING


# ─── loop termination ────────────────────────────────────────────────────────────────
def test_iteration_cap_stops_a_runaway_loop() -> None:
    result = run_investigation(TASK, _always_reads(), _registry(), max_iterations=1)
    assert result.state.status is RunStatus.LIMIT_EXCEEDED
    assert result.state.step == 1


def test_cost_budget_escalates_a_runaway_loop() -> None:
    adapter = _always_reads(CostTable(input_usd_per_mtok=10.0, output_usd_per_mtok=10.0))
    result = run_investigation(TASK, adapter, _registry(), max_iterations=6, max_cost_usd=1e-9)
    assert result.state.status is RunStatus.ESCALATED
    assert result.state.cost_usd > 0
