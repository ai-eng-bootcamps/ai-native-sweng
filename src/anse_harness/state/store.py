"""Versioned workflow state and checkpoint store on local files (spec 7.10; Lesson 5.5).

Persistence is what turns a loop into a workflow: every stage boundary saves a numbered
SNAPSHOT of the workflow state, so a later process can load the latest snapshot and
continue - or a human can audit exactly how the state evolved. The store also keeps the
workflow's ARTIFACTS (task specification, plan, patch, validation report, result) as
individual JSON documents, because the state schema references artifacts by identifier
and resume must be able to verify and reload them (architecture-reference 52).

Structured local JSON files, no external infrastructure (spec 7.10: "should not require
external infrastructure for foundational labs"); SQLite would buy nothing at this size.
Determinism is part of the contract: serialization is stable (sorted keys, fixed
indentation), directory iteration is sorted, and the snapshot timestamp comes from an
injectable clock so recorded runs are reproducible. Loading a snapshot whose state was
written under a different schema version fails loudly (``StateSchemaError`` raised by
``WorkflowState.from_payload``) - versioned state formats are the whole point.

Layout under the store root:

    <root>/<workflow_id>/snapshots/state-v0001.json   (one file per snapshot, envelope)
    <root>/<workflow_id>/artifacts/<artifact_id>.json (one file per artifact payload)

SCAFFOLDING: the envelope type, the error type, the stable serializer, and the path
conventions are supplied; implement the persistence methods in Module 5, Lesson 5.5.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anse_harness.workflows.state import WorkflowState

#: Snapshot filename shape; the four-digit version keeps lexical and numeric order equal.
_SNAPSHOT_PATTERN = re.compile(r"^state-v(\d{4,})\.json$")


class StateStoreError(Exception):
    """The store cannot satisfy a request (missing workflow, snapshot, or artifact)."""


@dataclass(frozen=True)
class Snapshot:
    """One persisted workflow-state snapshot: the envelope plus the state it carries."""

    version: int
    saved_at: str
    repository_revision: str
    state: WorkflowState


def _serialize(payload: dict[str, Any]) -> str:
    """Stable serialization: sorted keys, fixed indentation, trailing newline."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class WorkflowStateStore:
    """Persists versioned state snapshots and artifacts for workflows under one root."""

    def __init__(self, root: Path, *, clock: Callable[[], str] | None = None) -> None:
        self._root = root.resolve()
        self._clock = clock

    def _now(self) -> str:
        return self._clock() if self._clock is not None else datetime.now(UTC).isoformat()

    def _snapshot_dir(self, workflow_id: str) -> Path:
        return self._root / workflow_id / "snapshots"

    def _artifact_dir(self, workflow_id: str) -> Path:
        return self._root / workflow_id / "artifacts"

    def versions(self, workflow_id: str) -> tuple[int, ...]:
        """Every persisted snapshot version for a workflow, in ascending order."""
        raise NotImplementedError(
            "Module 5, Lesson 5.5: list the snapshot directory (sorted), match each "
            "entry against _SNAPSHOT_PATTERN, and return the version numbers in "
            "ascending order; a workflow with no snapshot directory has ()."
        )

    def next_version(self, workflow_id: str) -> int:
        """The version number the next ``save`` will be assigned (first save is 1)."""
        existing = self.versions(workflow_id)
        return (existing[-1] + 1) if existing else 1

    def save(self, state: WorkflowState, *, repository_revision: str) -> Snapshot:
        """Persist one snapshot of the state and return the stored envelope.

        Snapshots are append-only: each save is assigned the next version; an
        existing snapshot file is never overwritten.
        """
        raise NotImplementedError(
            "Module 5, Lesson 5.5: assign next_version(state.workflow_id); write "
            "_serialize({'snapshot_version': ..., 'saved_at': self._now(), "
            "'repository_revision': ..., 'state': state.to_payload()}) to "
            "state-v<NNNN>.json in the snapshot directory (create it; raise "
            "StateStoreError if the file already exists) and return the Snapshot."
        )

    def load(self, workflow_id: str, version: int) -> Snapshot:
        """Load one specific snapshot.

        Raises ``StateStoreError`` when the snapshot does not exist, and
        ``StateSchemaError`` (from ``WorkflowState.from_payload``) when the persisted
        state was written under a different schema version.
        """
        raise NotImplementedError(
            "Module 5, Lesson 5.5: read state-v<NNNN>.json (StateStoreError when "
            "missing), parse the envelope, and rebuild the state with "
            "WorkflowState.from_payload - which fails loudly on schema-version drift."
        )

    def load_latest(self, workflow_id: str) -> Snapshot:
        """Load the highest-versioned snapshot; raises when the workflow has none."""
        raise NotImplementedError(
            "Module 5, Lesson 5.5: load the highest version from versions(); raise "
            "StateStoreError when the workflow has no persisted snapshots."
        )

    def save_artifact(self, workflow_id: str, artifact_id: str, payload: dict[str, Any]) -> Path:
        """Persist one artifact payload and return its path (idempotent per identifier)."""
        raise NotImplementedError(
            "Module 5, Lesson 5.5: write _serialize(payload) to <artifact_id>.json "
            "in the artifact directory (create it) and return the path."
        )

    def has_artifact(self, workflow_id: str, artifact_id: str) -> bool:
        """Whether an artifact with this identifier is persisted."""
        return (self._artifact_dir(workflow_id) / f"{artifact_id}.json").is_file()

    def load_artifact(self, workflow_id: str, artifact_id: str) -> dict[str, Any]:
        """Load one artifact payload; raises ``StateStoreError`` when it is missing."""
        raise NotImplementedError(
            "Module 5, Lesson 5.5: read <artifact_id>.json (StateStoreError when "
            "missing or not a JSON object) and return the parsed payload."
        )
