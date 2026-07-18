"""The workflow transition table (Lesson 5.3; architecture-reference 19).

Valid transitions pass, everything else is rejected, terminal stages are dead ends,
and cancellation is reachable from every non-terminal stage. These fail against the
scaffolding stubs and pass once ``validate_transition`` is implemented to the
reference behaviour.
"""

import pytest

from anse_harness.workflows.engine import (
    TERMINAL_STAGES,
    TRANSITIONS,
    InvalidTransitionError,
    Stage,
    validate_transition,
)

pytestmark = pytest.mark.student_impl

#: The happy path of the Module 5 reference workflow, in order.
HAPPY_PATH = (
    (Stage.INTAKE, Stage.INVESTIGATE),
    (Stage.INVESTIGATE, Stage.PLAN),
    (Stage.PLAN, Stage.PLAN_APPROVAL),
    (Stage.PLAN_APPROVAL, Stage.IMPLEMENT),
    (Stage.IMPLEMENT, Stage.VALIDATE),
    (Stage.VALIDATE, Stage.PREPARE_RESULT),
    (Stage.PREPARE_RESULT, Stage.COMPLETED),
)


def test_the_happy_path_is_valid() -> None:
    for current, target in HAPPY_PATH:
        validate_transition(current, target)  # must not raise
    # The table itself covers every stage, and terminal stages allow nothing.
    assert set(TRANSITIONS) == set(Stage)
    for terminal in TERMINAL_STAGES:
        assert TRANSITIONS[terminal] == frozenset()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (Stage.INTAKE, Stage.IMPLEMENT),  # skipping investigation and planning
        (Stage.INVESTIGATE, Stage.IMPLEMENT),  # skipping planning and approval
        (Stage.PLAN, Stage.IMPLEMENT),  # skipping plan approval: approval is enforced
        (Stage.PLAN_APPROVAL, Stage.PREPARE_RESULT),  # skipping implementation
        (Stage.IMPLEMENT, Stage.COMPLETED),  # skipping validation
        (Stage.VALIDATE, Stage.COMPLETED),  # skipping result preparation
        (Stage.INVESTIGATE, Stage.INTAKE),  # backwards
        (Stage.INTAKE, Stage.INTAKE),  # self-loop
    ],
)
def test_invalid_transitions_are_rejected(current: Stage, target: Stage) -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(current, target)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STAGES))
@pytest.mark.parametrize("target", sorted(Stage))
def test_terminal_stages_are_dead_ends(terminal: Stage, target: Stage) -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(terminal, target)


@pytest.mark.parametrize("stage", sorted(set(Stage) - TERMINAL_STAGES))
def test_cancellation_is_reachable_from_every_non_terminal_stage(stage: Stage) -> None:
    validate_transition(stage, Stage.CANCELLED)  # must not raise
