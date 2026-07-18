"""Task-graph validation and deterministic ordering (Module 6, Lesson 6.3).

Exercises ``validate_task_graph`` (arch-ref 34: every check that must hold BEFORE any
worker runs) and ``graph_order`` (the deterministic topological order that schedules
fan-out and integration). These fail against the scaffolding stubs and pass once the
graph functions are implemented to the reference behaviour.
"""

import pytest

from anse_harness.workflows.graph import (
    TaskGraph,
    TaskGraphError,
    TaskNode,
    graph_order,
    validate_task_graph,
)

pytestmark = pytest.mark.student_impl


def _node(
    worker_id: str, *, depends_on: tuple[str, ...] = (), owned: tuple[str, ...] = ()
) -> TaskNode:
    return TaskNode(
        worker_id=worker_id,
        description=f"work for {worker_id}",
        acceptance_criteria=(f"{worker_id} done",),
        owned_paths=owned or (f"pkg/{worker_id}.go",),
        depends_on=depends_on,
    )


def test_graph_order_is_topological_with_declaration_order_tiebreak() -> None:
    graph = TaskGraph(
        task_id="t",
        nodes=(
            _node("d1"),
            _node("d3", depends_on=("d1",)),
            _node("d2", depends_on=("d1",)),
            _node("d4", depends_on=("d2", "d3")),
        ),
    )
    # d3 is declared before d2, so the tie between them breaks by declaration.
    assert graph_order(graph) == ("d1", "d3", "d2", "d4")


def test_graph_order_raises_on_cycle() -> None:
    graph = TaskGraph(
        task_id="t",
        nodes=(_node("a", depends_on=("b",)), _node("b", depends_on=("a",))),
    )
    with pytest.raises(TaskGraphError, match="cycle"):
        graph_order(graph)


@pytest.mark.parametrize(
    ("graph", "match"),
    [
        (TaskGraph(task_id="t", nodes=()), "no nodes"),
        (TaskGraph(task_id="t", nodes=(_node(""),)), "empty worker id"),
        (TaskGraph(task_id="t", nodes=(_node("a"), _node("a"))), "duplicate"),
        (TaskGraph(task_id="t", nodes=(_node("a", depends_on=("ghost",)),)), "unknown"),
        (TaskGraph(task_id="t", nodes=(_node("a", depends_on=("a",)),)), "itself"),
        (
            TaskGraph(
                task_id="t",
                nodes=(_node("a", depends_on=("b",)), _node("b", depends_on=("a",))),
            ),
            "cycle",
        ),
    ],
)
def test_validate_rejects_malformed_graphs(graph: TaskGraph, match: str) -> None:
    with pytest.raises(TaskGraphError, match=match):
        validate_task_graph(graph)


def test_validate_requires_clear_ownership_and_traceable_criteria() -> None:
    unowned = TaskNode(
        worker_id="a",
        description="d",
        acceptance_criteria=("done",),
        owned_paths=(),
    )
    with pytest.raises(TaskGraphError, match="owns no paths"):
        validate_task_graph(TaskGraph(task_id="t", nodes=(unowned,)))
    uncriterioned = TaskNode(
        worker_id="a",
        description="d",
        acceptance_criteria=(),
        owned_paths=("pkg/a.go",),
    )
    with pytest.raises(TaskGraphError, match="acceptance criteria"):
        validate_task_graph(TaskGraph(task_id="t", nodes=(uncriterioned,)))


def test_validate_enforces_a_feasible_worker_budget() -> None:
    graph = TaskGraph(task_id="t", nodes=(_node("a"), _node("b"), _node("c")))
    validate_task_graph(graph, max_workers=3)
    with pytest.raises(TaskGraphError, match="not feasible"):
        validate_task_graph(graph, max_workers=2)


def test_validate_identifies_ownership_overlap_without_forbidding_it() -> None:
    graph = TaskGraph(
        task_id="t",
        nodes=(
            _node("a", owned=("shared.go", "pkg/a.go")),
            _node("b", owned=("pkg/b.go",)),
            _node("c", owned=("shared.go",)),
        ),
    )
    overlaps = validate_task_graph(graph)
    assert len(overlaps) == 1
    assert overlaps[0].first_worker == "a"
    assert overlaps[0].second_worker == "c"
    assert overlaps[0].paths == ("shared.go",)
    disjoint = TaskGraph(task_id="t", nodes=(_node("a"), _node("b")))
    assert validate_task_graph(disjoint) == ()
