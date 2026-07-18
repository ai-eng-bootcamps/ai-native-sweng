"""The plan artifact and the planning stage's pinned rendering (Module 5).

The plan schema and the renderers are SUPPLIED infrastructure, so these tests run in
the default suite: they pin the artifact payload round trip, the model-text-to-steps
rule, and the deterministic renderings the recorded workflow trace replays against.
"""

from anse_harness.workflows.plan import (
    PlanArtifact,
    plan_steps_from_text,
    render_implementation_task,
    render_plan_request,
)


def _plan() -> PlanArtifact:
    return PlanArtifact(
        plan_id="plan-t-1",
        task_id="t-1",
        goal="Do the documented thing.",
        assumptions=(),
        steps=("1. Change the one line.", "2. Inspect the diff."),
        validation_strategy=("format-check: git diff --check",),
        risks=(),
        expected_artifacts=("patch", "validation_report"),
        stop_conditions=("implementation stops after at most 8 tool iterations",),
    )


def test_plan_payload_round_trip() -> None:
    plan = _plan()
    payload = plan.to_payload()
    assert payload["artifact_type"] == "plan"
    assert PlanArtifact.from_payload(payload) == plan


def test_plan_steps_are_the_non_empty_lines() -> None:
    text = "1. First step.\n\n  2. Second step.  \n"
    assert plan_steps_from_text(text) == ("1. First step.", "2. Second step.")
    assert plan_steps_from_text("\n \n") == ()


def test_plan_render_shows_every_populated_section() -> None:
    rendered = _plan().render()
    assert rendered.startswith("Plan plan-t-1 for task t-1")
    assert "Goal: Do the documented thing." in rendered
    assert "Steps:" in rendered
    assert "- 1. Change the one line." in rendered
    assert "Stop conditions:" in rendered
    assert "Assumptions:" not in rendered  # empty sections are omitted


def test_renderings_are_deterministic_functions_of_their_inputs() -> None:
    request = render_plan_request("t-1", "Do it.", ("It is done.",), "Findings.")
    assert request == render_plan_request("t-1", "Do it.", ("It is done.",), "Findings.")
    assert "Task t-1: Do it." in request
    assert "Acceptance criteria:" in request
    assert "1. It is done." in request
    assert "Investigation findings:" in request
    assert request.endswith("Reply with a numbered implementation plan, one step per line.")

    task_text = render_implementation_task("Do it.", ("It is done.",), _plan())
    assert task_text == render_implementation_task("Do it.", ("It is done.",), _plan())
    assert task_text.startswith("Do it.")
    assert "Approved plan:" in task_text
    assert "1. Change the one line." in task_text
    assert "sandbox worktree" in task_text
