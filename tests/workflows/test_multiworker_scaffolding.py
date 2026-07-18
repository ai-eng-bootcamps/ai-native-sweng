"""Multi-worker scaffolding: stage table, identifiers, and graph serialization.

The Module 6 stage graph, the worker-scoped artifact identifiers, the trace-file
naming, and the task-graph serialization are SUPPLIED infrastructure, so these tests
run in the default suite. The identifier tests pin the exact collision the Module 5
helpers would have under fan-out: two workers on one parent task need WORKER-scoped
artifact ids.
"""

import pytest

from anse_harness.workflows.graph import TaskGraph, TaskNode
from anse_harness.workflows.integration import changed_paths
from anse_harness.workflows.orchestrator import (
    MULTI_TERMINAL_STAGES,
    MULTI_TRANSITIONS,
    InvalidMultiTransitionError,
    MultiStage,
    invocation_artifact_id,
    validate_multiworker_transition,
    worker_patch_artifact_id,
    worker_trace_filename,
)


def test_task_graph_payload_round_trip() -> None:
    graph = TaskGraph(
        task_id="t-1",
        nodes=(
            TaskNode(
                worker_id="worker-a",
                description="do a",
                acceptance_criteria=("a done",),
                owned_paths=("pkg/a.go",),
                search_terms=("a",),
            ),
            TaskNode(
                worker_id="worker-b",
                description="do b",
                acceptance_criteria=("b done",),
                owned_paths=("pkg/b.go",),
                depends_on=("worker-a",),
            ),
        ),
    )
    payload = graph.to_payload()
    assert payload["artifact_type"] == "task_graph"
    assert TaskGraph.from_payload(payload) == graph


def test_terminal_stages_have_no_outgoing_transitions() -> None:
    for stage in MULTI_TERMINAL_STAGES:
        assert MULTI_TRANSITIONS[stage] == frozenset()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (MultiStage.INTAKE, MultiStage.REVIEW),
        (MultiStage.CONSOLIDATE, MultiStage.INTAKE),
        (MultiStage.COMPLETED, MultiStage.REVIEW),
        (MultiStage.FIX, MultiStage.PREPARE_RESULT),
    ],
)
def test_invalid_transitions_are_rejected(current: MultiStage, target: MultiStage) -> None:
    with pytest.raises(InvalidMultiTransitionError):
        validate_multiworker_transition(current, target)


def test_the_review_fix_loop_edges_are_legal() -> None:
    validate_multiworker_transition(MultiStage.FIX, MultiStage.VALIDATE)
    validate_multiworker_transition(MultiStage.VALIDATE, MultiStage.REVIEW)
    validate_multiworker_transition(MultiStage.CONSOLIDATE, MultiStage.FIX)
    validate_multiworker_transition(MultiStage.CONSOLIDATE, MultiStage.PREPARE_RESULT)


def test_artifact_ids_are_worker_scoped() -> None:
    # The Module 5 helpers are task+attempt scoped and would collide across
    # workers of one parent task; the Module 6 ids carry the worker segment.
    assert worker_patch_artifact_id("t-1", "worker-a", 1) != worker_patch_artifact_id(
        "t-1", "worker-b", 1
    )
    assert invocation_artifact_id("reviewer-1", "review", 1) != invocation_artifact_id(
        "reviewer-1", "review", 2
    )


def test_worker_trace_filenames_map_invocations_to_files() -> None:
    assert worker_trace_filename("worker-a") == "worker_a.jsonl"
    assert worker_trace_filename("reviewer-1", 1) == "reviewer_1.jsonl"
    assert worker_trace_filename("reviewer-1", 2) == "reviewer_1_round_2.jsonl"


def test_changed_paths_reads_both_diff_headers_once() -> None:
    diff = (
        "diff --git a/pkg/a.go b/pkg/a.go\n"
        "--- a/pkg/a.go\n"
        "+++ b/pkg/a.go\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
        "diff --git a/pkg/gone.go b/pkg/gone.go\n"
        "--- a/pkg/gone.go\n"
        "+++ /dev/null\n"
    )
    assert changed_paths(diff) == ("pkg/a.go", "pkg/gone.go")
