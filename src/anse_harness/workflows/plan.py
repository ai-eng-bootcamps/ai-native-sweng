"""The plan artifact and the planning stage's deterministic rendering (Module 5).

Planning produces a structured artifact, not loose prose (architecture-reference 32):
the plan carries the goal, the steps, the validation strategy, and the stop conditions
the implementation stage will run under. In the reference workflow the plan's STEPS
come from one model call (planning is a judgment step, Lesson 5.4) while every other
field is filled deterministically from the task specification and the workflow
configuration - the boundary between model judgment and deterministic assembly is
drawn on purpose, and the whole artifact is what the plan-approval boundary shows a
human before implementation may begin.

Rendering is pinned: ``PLAN_SYSTEM_PROMPT`` is a module constant and the request and
implementation-task renderers are pure functions of their inputs, so a recorded
workflow run replays byte-stable (the Module 2 pinning discipline, unchanged).

SUPPLIED infrastructure: the artifact schema and the renderers are consumed as-is;
the engine that calls them (``workflows/engine.py``) is yours to implement in
Module 5.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: Pinned system prompt for the planning stage's single model call. Building this per
#: run would change the recorded request and break replay.
PLAN_SYSTEM_PROMPT = (
    "You are the planning stage of a staged engineering workflow. Produce a short, "
    "numbered implementation plan for the task, grounded in the investigation findings "
    "you are given. One step per line. Do not implement anything and do not call any "
    "tools; reply with the plan text only."
)


@dataclass(frozen=True)
class PlanArtifact:
    """One reviewable plan (architecture-reference 32): what will be done, and when to stop."""

    plan_id: str
    task_id: str
    goal: str
    assumptions: tuple[str, ...]
    steps: tuple[str, ...]
    validation_strategy: tuple[str, ...]
    risks: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Serialize for trace payloads (artifact_created) and the artifact store."""
        return {
            "artifact_type": "plan",
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "goal": self.goal,
            "assumptions": list(self.assumptions),
            "steps": list(self.steps),
            "validation_strategy": list(self.validation_strategy),
            "risks": list(self.risks),
            "expected_artifacts": list(self.expected_artifacts),
            "stop_conditions": list(self.stop_conditions),
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> PlanArtifact:
        """Deserialize one payload back into a PlanArtifact."""
        return cls(
            plan_id=str(data["plan_id"]),
            task_id=str(data["task_id"]),
            goal=str(data["goal"]),
            assumptions=tuple(str(item) for item in data.get("assumptions", [])),
            steps=tuple(str(item) for item in data.get("steps", [])),
            validation_strategy=tuple(str(item) for item in data.get("validation_strategy", [])),
            risks=tuple(str(item) for item in data.get("risks", [])),
            expected_artifacts=tuple(str(item) for item in data.get("expected_artifacts", [])),
            stop_conditions=tuple(str(item) for item in data.get("stop_conditions", [])),
        )

    def render(self) -> str:
        """Render the plan as the human-readable text the approval boundary shows.

        This rendering is what goes into the plan approval request's proposed-change
        field (spec 7.14: a request carries the "diff or proposed change").
        """
        lines = [f"Plan {self.plan_id} for task {self.task_id}", "", f"Goal: {self.goal}"]
        for heading, items in (
            ("Assumptions", self.assumptions),
            ("Steps", self.steps),
            ("Validation strategy", self.validation_strategy),
            ("Risks", self.risks),
            ("Expected artifacts", self.expected_artifacts),
            ("Stop conditions", self.stop_conditions),
        ):
            if items:
                lines.append("")
                lines.append(f"{heading}:")
                lines.extend(f"- {item}" for item in items)
        return "\n".join(lines)


def plan_steps_from_text(text: str) -> tuple[str, ...]:
    """The plan steps a model reply carries: its non-empty lines, in order, stripped."""
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def render_plan_request(
    task_id: str,
    description: str,
    acceptance_criteria: Sequence[str],
    investigation_answer: str,
) -> str:
    """Render the planning stage's user message: task, criteria, and findings.

    A pure function of its inputs, so the recorded planning request replays
    byte-stable.
    """
    lines = [f"Task {task_id}: {description}"]
    if acceptance_criteria:
        lines.append("")
        lines.append("Acceptance criteria:")
        lines.extend(
            f"{i}. {criterion}" for i, criterion in enumerate(acceptance_criteria, start=1)
        )
    lines.append("")
    lines.append("Investigation findings:")
    lines.append(investigation_answer.rstrip())
    lines.append("")
    lines.append("Reply with a numbered implementation plan, one step per line.")
    return "\n".join(lines)


def render_implementation_task(
    description: str,
    acceptance_criteria: Sequence[str],
    plan: PlanArtifact,
) -> str:
    """Render the task text the implementation stage hands to the write run.

    The implementer receives the task, the criteria, and the APPROVED plan steps - not
    the planning conversation. A pure function of its inputs, so the recorded
    implementation requests replay byte-stable.
    """
    lines = [description]
    if acceptance_criteria:
        lines.append("")
        lines.append("Acceptance criteria:")
        lines.extend(
            f"{i}. {criterion}" for i, criterion in enumerate(acceptance_criteria, start=1)
        )
    lines.append("")
    lines.append("Approved plan:")
    lines.extend(plan.steps)
    lines.append("")
    lines.append(
        "Work only inside your sandbox worktree, follow the approved plan, inspect "
        "your diff before finishing, and finish with a short summary of the change "
        "you propose."
    )
    return "\n".join(lines)
