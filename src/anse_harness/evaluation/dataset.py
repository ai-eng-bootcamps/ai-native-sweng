"""Task-dataset loading: manifests, partitions, and explicit dataset descriptors (spec 13.2-13.4).

An evaluation is only as trustworthy as its task set, and the task set is governed by
the partition discipline of Lesson 8.2: practice tasks are for learning the harness,
development tasks are for building and tuning configurations, and held-out tasks exist
so that a claimed improvement can be tested on work the configuration was never tuned
against. A loader that quietly hands out held-out tasks destroys that separation - once
a held-out task has leaked into development, it can never be held out again. The loader
therefore EXCLUDES the held-out partition by default; surfacing a held-out task is an
explicit, visible decision (``include_held_out=True``), never a side effect.

Datasets themselves are declared as explicit id lists (``DatasetDescriptor``), not as
module-tag filters: the manifest ``modules`` arrays describe where a task is taught,
which is not the same question as which tasks an evaluation runs. An explicit list is
reviewable, diffable, and stable when manifests gain or lose tags. The descriptor is
validated against the manifests at load time, so a typo or a partition drift fails
loudly instead of silently shrinking the dataset.

SCAFFOLDING: the manifest and descriptor schemas are supplied; implement
``load_manifests`` and ``load_dataset`` in Module 8, Lesson 8.2.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The three dataset partitions of spec 13.2, in escalating exposure sensitivity.
PARTITIONS: tuple[str, ...] = ("practice", "development", "held-out")

#: The partition the loader never surfaces unless explicitly asked to.
HELD_OUT_PARTITION = "held-out"

#: The manifest schema file that lives beside the task manifests and must be skipped.
MANIFEST_SCHEMA_FILENAME = "task-manifest.schema.json"


class DatasetError(Exception):
    """A dataset declaration does not match the manifests it claims to describe."""


@dataclass(frozen=True)
class TaskManifest:
    """One task manifest (spec 13.3), reduced to the fields the evaluation harness uses.

    ``raw`` preserves the complete manifest payload for consumers that need fields
    beyond this projection (rubrics, ambiguities, expected failure modes).
    """

    task_id: str
    title: str
    category: str
    partition: str
    modules: tuple[str, ...]
    repository: str
    starting_revision: str
    description: str
    baseline_configuration: str
    hidden_validation: str
    visible_validation: tuple[dict[str, Any], ...]
    raw: dict[str, Any]

    def __post_init__(self) -> None:
        if self.partition not in PARTITIONS:
            raise DatasetError(
                f"manifest {self.task_id!r} has unknown partition {self.partition!r}"
            )

    @property
    def visible_commands(self) -> tuple[str, ...]:
        """The command-kind visible validation entries, in manifest order."""
        return tuple(
            str(entry["command"])
            for entry in self.visible_validation
            if entry.get("kind") == "command"
        )

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> TaskManifest:
        """Build a manifest from one parsed manifest JSON payload."""
        return cls(
            task_id=str(data["id"]),
            title=str(data["title"]),
            category=str(data["category"]),
            partition=str(data["partition"]),
            modules=tuple(str(m) for m in data["modules"]),
            repository=str(data["repository"]),
            starting_revision=str(data["starting_revision"]),
            description=str(data["description"]),
            baseline_configuration=str(data["baseline_configuration"]),
            hidden_validation=str(data["hidden_validation"]),
            visible_validation=tuple(dict(entry) for entry in data["visible_validation"]),
            raw=dict(data),
        )

    @classmethod
    def from_file(cls, path: Path) -> TaskManifest:
        """Load one manifest file."""
        return cls.from_payload(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class DatasetDescriptor:
    """An explicit, reviewable dataset declaration: which tasks, and what they must be.

    ``expected_partition`` pins the partition every listed task must belong to; a task
    whose manifest has drifted to another partition fails the load instead of silently
    changing what the evaluation measures.
    """

    dataset_id: str
    description: str
    task_ids: tuple[str, ...]
    expected_partition: str

    def __post_init__(self) -> None:
        if self.expected_partition not in PARTITIONS:
            raise DatasetError(
                f"dataset {self.dataset_id!r} expects unknown partition {self.expected_partition!r}"
            )
        if not self.task_ids:
            raise DatasetError(f"dataset {self.dataset_id!r} lists no tasks")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise DatasetError(f"dataset {self.dataset_id!r} lists a task more than once")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the committed descriptor file."""
        return {
            "dataset_id": self.dataset_id,
            "description": self.description,
            "task_ids": list(self.task_ids),
            "expected_partition": self.expected_partition,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> DatasetDescriptor:
        """Deserialize one descriptor payload."""
        return cls(
            dataset_id=str(data["dataset_id"]),
            description=str(data["description"]),
            task_ids=tuple(str(t) for t in data["task_ids"]),
            expected_partition=str(data["expected_partition"]),
        )

    @classmethod
    def from_file(cls, path: Path) -> DatasetDescriptor:
        """Load one committed descriptor file (e.g. ``configs/evaluation/m08-lab.json``)."""
        return cls.from_payload(json.loads(path.read_text(encoding="utf-8")))


def load_manifests(
    manifest_dir: Path, *, include_held_out: bool = False
) -> tuple[TaskManifest, ...]:
    """Load every task manifest in ``manifest_dir``, excluding held-out by default.

    Returns manifests sorted by filename. The schema file
    (``MANIFEST_SCHEMA_FILENAME``) is not a manifest and is skipped. Manifests whose
    partition is ``held-out`` are returned ONLY when ``include_held_out`` is True -
    surfacing a held-out task is an explicit decision, never a default.
    """
    raise NotImplementedError(
        "Module 8, Lesson 8.2: glob '*.json' in manifest_dir sorted by name, skip "
        "MANIFEST_SCHEMA_FILENAME, parse each with TaskManifest.from_file, and drop "
        "manifests in the held-out partition unless include_held_out is True."
    )


def load_dataset(
    descriptor: DatasetDescriptor,
    manifest_dir: Path,
    *,
    include_held_out: bool = False,
) -> tuple[TaskManifest, ...]:
    """Resolve a dataset descriptor against the manifests, validating every claim.

    Returns the manifests in DESCRIPTOR order (the dataset defines the matrix order).
    Raises ``DatasetError`` when a listed task has no manifest, when a manifest's
    partition differs from ``descriptor.expected_partition``, or when a listed task is
    held-out and ``include_held_out`` is False - a held-out task never travels into an
    evaluation implicitly, even via an explicit id list.
    """
    raise NotImplementedError(
        "Module 8, Lesson 8.2: load ALL manifests (including held-out - exclusion is "
        "decided here, not hidden by the underlying loader), index them by id, then "
        "resolve descriptor.task_ids in order; raise DatasetError for unknown ids, for "
        "partition mismatches against expected_partition, and for held-out tasks when "
        "include_held_out is False."
    )
