"""Dataset loading exercises (Lesson 8.2): partition discipline over the REAL manifests.

Held-out exclusion is the load-bearing behavior: a loader that hands out held-out
tasks by default has already destroyed the partition it was supposed to protect.
"""

from pathlib import Path

import pytest

from anse_harness.evaluation.dataset import (
    DatasetDescriptor,
    DatasetError,
    load_dataset,
    load_manifests,
)

pytestmark = pytest.mark.student_impl

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = REPO_ROOT / "datasets" / "manifests"
DESCRIPTOR = DatasetDescriptor.from_file(REPO_ROOT / "configs" / "evaluation" / "m08-lab.json")


def test_default_load_excludes_the_held_out_partition() -> None:
    manifests = load_manifests(MANIFESTS)
    ids = {m.task_id for m in manifests}
    assert ids, "the real manifest directory must load"
    assert all(m.partition != "held-out" for m in manifests)
    assert "bk-011" not in ids and "bk-012" not in ids
    # The schema file beside the manifests is not a manifest.
    assert all(not m.task_id.endswith(".schema") for m in manifests)


def test_held_out_surfaces_only_on_explicit_request() -> None:
    everything = load_manifests(MANIFESTS, include_held_out=True)
    ids = {m.task_id for m in everything}
    assert "bk-011" in ids and "bk-012" in ids
    held_out = [m for m in everything if m.partition == "held-out"]
    assert {m.task_id for m in held_out} == {"bk-011", "bk-012"}
    # Explicit inclusion is a superset of the default load.
    assert ids > {m.task_id for m in load_manifests(MANIFESTS)}


def test_manifests_are_returned_in_filename_order() -> None:
    manifests = load_manifests(MANIFESTS)
    ids = [m.task_id for m in manifests]
    assert ids == sorted(ids)


def test_lab_descriptor_resolves_exactly_its_six_tasks_in_order() -> None:
    dataset = load_dataset(DESCRIPTOR, MANIFESTS)
    assert [m.task_id for m in dataset] == list(DESCRIPTOR.task_ids)
    assert all(m.partition == "development" for m in dataset)


def test_lab_dataset_tasks_declare_their_hidden_graders() -> None:
    dataset = load_dataset(DESCRIPTOR, MANIFESTS)
    for manifest in dataset:
        assert manifest.hidden_validation == f"grader:{manifest.task_id}"
        assert manifest.baseline_configuration in ("C", "D")
        assert manifest.visible_commands, "every lab task publishes visible checks"


def test_unknown_task_id_fails_loudly() -> None:
    descriptor = DatasetDescriptor("d", "x", ("bk-003", "bk-999"), "development")
    with pytest.raises(DatasetError, match="bk-999"):
        load_dataset(descriptor, MANIFESTS)


def test_partition_drift_fails_loudly() -> None:
    # bk-001 is a practice task; a development-partition dataset must refuse it.
    descriptor = DatasetDescriptor("d", "x", ("bk-001",), "development")
    with pytest.raises(DatasetError, match="partition"):
        load_dataset(descriptor, MANIFESTS)


def test_held_out_task_in_a_dataset_requires_the_explicit_flag() -> None:
    reveal = DatasetDescriptor("m08-reveal", "the held-out reveal", ("bk-011",), "held-out")
    with pytest.raises(DatasetError, match="held-out"):
        load_dataset(reveal, MANIFESTS)
    revealed = load_dataset(reveal, MANIFESTS, include_held_out=True)
    assert [m.task_id for m in revealed] == ["bk-011"]
    assert revealed[0].partition == "held-out"
