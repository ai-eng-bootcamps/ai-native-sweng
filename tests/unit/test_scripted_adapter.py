"""Unit tests for the scripted model mode (spec 5.3, 7.16: scripted-response support)."""

from pathlib import Path

import pytest

from anse_harness.models import (
    CostTable,
    Message,
    ModelRequest,
    ModelResponse,
    ScriptedAdapter,
    ScriptExhaustedError,
    ScriptMismatchError,
    ScriptStep,
    Usage,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _request(text: str) -> ModelRequest:
    return ModelRequest(messages=[Message("user", text)])


def test_returns_scripted_responses_in_order() -> None:
    adapter = ScriptedAdapter(
        [
            ScriptStep(response=ModelResponse(text="first")),
            ScriptStep(response=ModelResponse(text="second")),
        ]
    )
    assert adapter.complete(_request("a")).text == "first"
    assert adapter.complete(_request("b")).text == "second"


def test_script_exhaustion_raises() -> None:
    adapter = ScriptedAdapter([ScriptStep(response=ModelResponse(text="only"))])
    adapter.complete(_request("a"))
    with pytest.raises(ScriptExhaustedError):
        adapter.complete(_request("b"))


def test_expectation_mismatch_raises() -> None:
    adapter = ScriptedAdapter(
        [ScriptStep(response=ModelResponse(text="x"), expect_substring="expected words")]
    )
    with pytest.raises(ScriptMismatchError):
        adapter.complete(_request("something else entirely"))


def test_expectation_match_passes() -> None:
    adapter = ScriptedAdapter(
        [ScriptStep(response=ModelResponse(text="x"), expect_substring="expected words")]
    )
    assert adapter.complete(_request("these are the expected words")).text == "x"


def test_from_file_loads_committed_demo_script() -> None:
    adapter = ScriptedAdapter.from_file(REPO_ROOT / "configs" / "models" / "scripted-demo.json")
    response = adapter.complete(_request("Map the reservation lifecycle."))
    assert response.stop_reason == "tool_use"
    assert response.tool_calls[0].name == "list_files"


def test_cost_calculation_hook() -> None:
    adapter = ScriptedAdapter(
        [], cost_table=CostTable(input_usd_per_mtok=5.0, output_usd_per_mtok=25.0)
    )
    cost = adapter.calculate_cost(Usage(input_tokens=1_000_000, output_tokens=200_000))
    assert cost == pytest.approx(5.0 + 5.0)


def test_capabilities_metadata() -> None:
    caps = ScriptedAdapter([]).capabilities()
    assert caps.supports_tools
    assert caps.supports_structured_output
    assert caps.cost_class == "free"
