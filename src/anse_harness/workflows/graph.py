"""Task graph: dependency-aware decomposition of one feature task (Lesson 6.3).

Decomposition turns one feature into bounded sub-tasks with useful independence
(arch-ref 33): each node names its worker, its sub-task, its acceptance criteria, the
paths it OWNS, and the nodes it depends on. The graph is a first-class artifact - the
orchestrator persists it, validates it before any worker runs (arch-ref 34), and
derives the integration order from it (arch-ref 37 step 4: order patches by
dependency).

Ownership is the overlap-avoidance mechanism: two nodes that own the same path are not
forbidden, but the overlap must be IDENTIFIED at validation time so integration knows
to expect it (arch-ref 34: "affected-file overlap is identified"; the overlap POLICY
that classifies it lives in ``workflows/integration.py``).

SCAFFOLDING: the graph schema and serialization are supplied; implement
``validate_task_graph`` and ``graph_order`` in Module 6, Lesson 6.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TaskGraphError(Exception):
    """The task graph is invalid (arch-ref 34): correct it or escalate, never run it."""


@dataclass(frozen=True)
class TaskNode:
    """One sub-task of the decomposition: bounded work owned by one worker."""

    worker_id: str
    description: str
    acceptance_criteria: tuple[str, ...]
    #: Repository-relative paths this node's change is expected to touch. Ownership
    #: must be clear (arch-ref 34); overlap across nodes is identified at validation.
    owned_paths: tuple[str, ...]
    #: Worker ids this node depends on; dependencies define the integration order.
    depends_on: tuple[str, ...] = ()
    #: Search terms for the worker's context packet (derived from the description
    #: when omitted, exactly like Module 5's task specification).
    search_terms: tuple[str, ...] | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the task-graph artifact."""
        return {
            "worker_id": self.worker_id,
            "description": self.description,
            "acceptance_criteria": list(self.acceptance_criteria),
            "owned_paths": list(self.owned_paths),
            "depends_on": list(self.depends_on),
            "search_terms": None if self.search_terms is None else list(self.search_terms),
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> TaskNode:
        """Deserialize one task-graph node payload."""
        terms = data.get("search_terms")
        return cls(
            worker_id=str(data["worker_id"]),
            description=str(data["description"]),
            acceptance_criteria=tuple(str(item) for item in data.get("acceptance_criteria", [])),
            owned_paths=tuple(str(item) for item in data.get("owned_paths", [])),
            depends_on=tuple(str(item) for item in data.get("depends_on", [])),
            search_terms=None if terms is None else tuple(str(item) for item in terms),
        )


@dataclass(frozen=True)
class OwnershipOverlap:
    """Two nodes that declare ownership of the same paths (identified, not forbidden)."""

    first_worker: str
    second_worker: str
    paths: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the task-graph artifact."""
        return {
            "first_worker": self.first_worker,
            "second_worker": self.second_worker,
            "paths": list(self.paths),
        }


@dataclass(frozen=True)
class TaskGraph:
    """The dependency-aware decomposition of one feature task (Lesson 6.3)."""

    task_id: str
    nodes: tuple[TaskNode, ...]

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the task-graph artifact."""
        return {
            "artifact_type": "task_graph",
            "task_id": self.task_id,
            "nodes": [node.to_payload() for node in self.nodes],
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> TaskGraph:
        """Deserialize one task-graph artifact payload."""
        return cls(
            task_id=str(data["task_id"]),
            nodes=tuple(TaskNode.from_payload(dict(item)) for item in data.get("nodes", [])),
        )


def validate_task_graph(
    graph: TaskGraph, *, max_workers: int | None = None
) -> tuple[OwnershipOverlap, ...]:
    """Validate the graph before execution and identify ownership overlap (arch-ref 34).

    Raises ``TaskGraphError`` when: the graph has no nodes; a node's worker id is
    empty or duplicated; a dependency names an unknown worker id (or the node
    itself); the dependency graph has a cycle; a node owns no paths (ownership must
    be clear); a node has no acceptance criteria (criteria must be traceable); or
    ``max_workers`` is set and the node count exceeds it (the worker budget must be
    feasible before fan-out, spec 7.15).

    Returns the identified ownership overlaps - every pair of nodes that declare one
    or more of the same owned paths, in node order. Overlap is identified here and
    classified by the integration policy, not silently discovered at apply time.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.3: check node presence, unique non-empty worker ids, "
        "known and non-self dependencies, acyclicity (graph_order raises on a "
        "cycle), non-empty owned_paths and acceptance_criteria per node, and the "
        "max_workers budget; then return the pairwise ownership overlaps in node "
        "order."
    )


def graph_order(graph: TaskGraph) -> tuple[str, ...]:
    """The deterministic execution and integration order of the graph's workers.

    A topological order over ``depends_on``: every node appears after all of its
    dependencies, and ties are broken by node declaration order, so the same graph
    always yields the same order - scripted and replayed runs schedule fan-out in
    exactly this order, and patches are applied to the integration worktree in
    exactly this order (arch-ref 37). Raises ``TaskGraphError`` when the
    dependencies contain a cycle or name unknown workers.
    """
    raise NotImplementedError(
        "Module 6, Lesson 6.3: Kahn's algorithm with node declaration order as the "
        "tie-break: repeatedly take the first declared node whose dependencies are "
        "all satisfied; raise TaskGraphError when none is available (cycle) or a "
        "dependency is unknown."
    )
