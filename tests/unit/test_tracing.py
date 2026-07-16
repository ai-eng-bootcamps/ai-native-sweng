"""Unit tests for the trace event schema and JSONL round trip (spec 19)."""

from pathlib import Path

import pytest

from anse_harness.tracing import EVENT_TYPES, TraceEvent, TraceWriter, read_trace


def _event(**overrides: object) -> TraceEvent:
    kwargs: dict[str, object] = {
        "run_id": "run-1",
        "workflow_id": "wf-1",
        "component": "models",
        "event_type": "model_requested",
        "status": "ok",
        "payload": {"request": {"messages": []}},
    }
    kwargs.update(overrides)
    return TraceEvent(**kwargs)  # type: ignore[arg-type]


def test_event_vocabulary_matches_spec_section_19() -> None:
    assert "run_started" in EVENT_TYPES
    assert "policy_evaluated" in EVENT_TYPES
    assert "budget_exhausted" in EVENT_TYPES
    assert "artifact_created" in EVENT_TYPES
    assert len(EVENT_TYPES) == 25


def test_unknown_event_type_rejected() -> None:
    with pytest.raises(ValueError, match="unknown trace event type"):
        _event(event_type="model_pondered")


def test_sensitivity_classification_present_and_validated() -> None:
    assert _event().sensitivity == "public"
    assert _event(sensitivity="sensitive").sensitivity == "sensitive"
    with pytest.raises(ValueError, match="unknown sensitivity level"):
        _event(sensitivity="top-secret")


def test_serialization_round_trip(tmp_path: Path) -> None:
    events = [
        _event(event_id="a"),
        _event(
            event_id="b",
            event_type="model_responded",
            parent_event_id="a",
            payload={"response": {"text": "hi"}},
            sensitivity="sensitive",
        ),
    ]
    path = tmp_path / "trace.jsonl"
    with TraceWriter(path) as writer:
        for event in events:
            writer.write(event)

    loaded = read_trace(path)
    assert loaded == events


def test_serialized_event_carries_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    with TraceWriter(path) as writer:
        writer.write(_event())
    (loaded,) = read_trace(path)
    data = loaded.to_dict()
    for required in (
        "timestamp",
        "run_id",
        "workflow_id",
        "component",
        "event_type",
        "status",
        "parent_event_id",
        "payload",
        "sensitivity",
    ):
        assert required in data
