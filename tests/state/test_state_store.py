"""The versioned workflow state store (Lesson 5.5).

Snapshots are numbered, append-only, deterministically serialized, and loud about
schema-version drift; artifacts round-trip by identifier. These fail against the
scaffolding stubs and pass once the store is implemented to the reference behaviour.
"""

import json
from pathlib import Path

import pytest

from anse_harness.state.store import StateStoreError, WorkflowStateStore
from anse_harness.workflows.state import (
    StateSchemaError,
    WorkflowState,
    WorkflowStatus,
    initial_workflow_state,
)

pytestmark = pytest.mark.student_impl

CLOCK = "2026-01-01T00:00:00+00:00"


def _state(workflow_id: str = "wf-1") -> WorkflowState:
    return initial_workflow_state(
        workflow_id,
        workflow_type="feature-task",
        workflow_version="1",
        task_id="t-1",
        termination_policy="explicit terminal stage required",
        approval_policy="deny by default",
    )


def _store(root: Path) -> WorkflowStateStore:
    return WorkflowStateStore(root, clock=lambda: CLOCK)


def test_save_assigns_sequential_versions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _state()
    assert store.versions("wf-1") == ()
    assert store.next_version("wf-1") == 1

    first = store.save(state, repository_revision="rev-a")
    assert first.version == 1
    state.status.state = WorkflowStatus.RUNNING
    second = store.save(state, repository_revision="rev-a")
    assert second.version == 2
    assert store.versions("wf-1") == (1, 2)
    assert store.next_version("wf-1") == 3
    assert (tmp_path / "wf-1" / "snapshots" / "state-v0001.json").is_file()
    assert (tmp_path / "wf-1" / "snapshots" / "state-v0002.json").is_file()


def test_serialization_is_deterministic(tmp_path: Path) -> None:
    """Equal states saved through pinned clocks produce byte-identical snapshots."""
    store_a = _store(tmp_path / "a")
    store_b = _store(tmp_path / "b")
    store_a.save(_state(), repository_revision="rev-a")
    store_b.save(_state(), repository_revision="rev-a")
    bytes_a = (tmp_path / "a" / "wf-1" / "snapshots" / "state-v0001.json").read_bytes()
    bytes_b = (tmp_path / "b" / "wf-1" / "snapshots" / "state-v0001.json").read_bytes()
    assert bytes_a == bytes_b


def test_load_round_trips_the_snapshot_envelope(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _state()
    saved = store.save(state, repository_revision="rev-a")
    loaded = store.load("wf-1", saved.version)
    assert loaded.version == 1
    assert loaded.saved_at == CLOCK
    assert loaded.repository_revision == "rev-a"
    assert loaded.state == state


def test_load_latest_returns_the_highest_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _state()
    store.save(state, repository_revision="rev-a")
    state.status.state = WorkflowStatus.RUNNING
    state.status.current_stage = "investigate"
    store.save(state, repository_revision="rev-a")
    latest = store.load_latest("wf-1")
    assert latest.version == 2
    assert latest.state.status.current_stage == "investigate"


def test_missing_snapshots_fail_loudly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(StateStoreError):
        store.load_latest("wf-unknown")
    store.save(_state(), repository_revision="rev-a")
    with pytest.raises(StateStoreError):
        store.load("wf-1", 7)


def test_schema_version_drift_on_disk_fails_loudly(tmp_path: Path) -> None:
    """A snapshot written under another schema version must never load quietly."""
    store = _store(tmp_path)
    store.save(_state(), repository_revision="rev-a")
    path = tmp_path / "wf-1" / "snapshots" / "state-v0001.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["state"]["schema_version"] = "999"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StateSchemaError):
        store.load_latest("wf-1")


def test_artifacts_round_trip_by_identifier(tmp_path: Path) -> None:
    store = _store(tmp_path)
    payload = {"artifact_type": "plan", "plan_id": "plan-t-1", "steps": ["1. Do it."]}
    assert not store.has_artifact("wf-1", "plan-t-1")
    path = store.save_artifact("wf-1", "plan-t-1", payload)
    assert path.is_file()
    assert store.has_artifact("wf-1", "plan-t-1")
    assert store.load_artifact("wf-1", "plan-t-1") == payload
    with pytest.raises(StateStoreError):
        store.load_artifact("wf-1", "missing-artifact")
