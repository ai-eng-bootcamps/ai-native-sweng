"""Grader exercises (Lessons 8.3-8.4): visible-validation and model-assisted grading.

The student-side deterministic grader runs the manifest's OWN published checks; the
model-assisted grader is adapter-shaped, costs nothing under a scripted adapter, and
treats an unparseable judge reply as an infrastructure error - never as a grade.
"""

from pathlib import Path
from typing import Any

import pytest

from anse_harness.evaluation.dataset import TaskManifest
from anse_harness.evaluation.graders import (
    MODEL_GRADER_SYSTEM_PROMPT,
    ModelAssistedGrader,
    VisibleValidationGrader,
)
from anse_harness.models import (
    ModelAdapter,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ScriptedAdapter,
    ScriptStep,
    Usage,
)

pytestmark = pytest.mark.student_impl


class _SpyJudge(ModelAdapter):
    """Records every request it forwards to an inner scripted judge."""

    def __init__(self, inner: ScriptedAdapter) -> None:
        super().__init__()
        self.inner = inner
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.inner.complete(request)

    def capabilities(self) -> ModelCapabilities:
        return self.inner.capabilities()


def _manifest(visible: list[dict[str, Any]]) -> TaskManifest:
    return TaskManifest.from_payload(
        {
            "id": "fx-grade",
            "title": "grading fixture",
            "category": "defect-fix",
            "partition": "development",
            "modules": ["M8"],
            "repository": "fixture",
            "starting_revision": "0" * 40,
            "description": "grading fixture task",
            "baseline_configuration": "D",
            "hidden_validation": "grader:fx-grade",
            "visible_validation": visible,
        }
    )


def test_visible_validation_passes_when_every_command_passes(tmp_path: Path) -> None:
    manifest = _manifest(
        [
            {"kind": "command", "command": "git --version", "description": "git available"},
            {"kind": "artifact", "description": "diff adds tests only"},
        ]
    )
    grader = VisibleValidationGrader(manifest)
    result = grader.grade(tmp_path)
    assert result.passed is True
    assert result.exit_code == 0
    assert result.grader_id == "visible:fx-grade"
    assert result.grader_version == grader.version
    # The artifact-kind entry is reported for human review, never executed.
    assert "human review: diff adds tests only" in result.output


def test_visible_validation_fails_on_the_first_failing_command(tmp_path: Path) -> None:
    manifest = _manifest(
        [
            {"kind": "command", "command": "git --version", "description": "ok"},
            {"kind": "command", "command": "git frobnicate", "description": "fails"},
        ]
    )
    result = VisibleValidationGrader(manifest).grade(tmp_path)
    assert result.passed is False
    assert result.infrastructure is False
    assert result.exit_code not in (0, None)


def test_visible_validation_unlaunchable_command_is_infrastructure(tmp_path: Path) -> None:
    manifest = _manifest(
        [{"kind": "command", "command": "definitely-not-a-command-anse", "description": "x"}]
    )
    result = VisibleValidationGrader(manifest).grade(tmp_path)
    assert result.infrastructure is True
    assert result.passed is None


def test_visible_validation_version_tracks_the_command_list(tmp_path: Path) -> None:
    a = VisibleValidationGrader(
        _manifest([{"kind": "command", "command": "git --version", "description": "x"}])
    )
    b = VisibleValidationGrader(
        _manifest([{"kind": "command", "command": "git version", "description": "x"}])
    )
    assert a.version != b.version
    # The version travels on every result the grader produces.
    assert a.grade(tmp_path).grader_version == a.version


def _judge(reply: str) -> ScriptedAdapter:
    return ScriptedAdapter(
        [
            ScriptStep(
                response=ModelResponse(
                    text=reply,
                    stop_reason="end_turn",
                    usage=Usage(input_tokens=100, output_tokens=20),
                )
            )
        ]
    )


def test_model_assisted_grader_parses_the_verdict(tmp_path: Path) -> None:
    (tmp_path / "report.md").write_text("The change is correct.\n", encoding="utf-8")
    collected: list[Path] = []

    def collect(workdir: Path) -> str:
        collected.append(workdir)
        return (workdir / "report.md").read_text(encoding="utf-8")

    grader = ModelAssistedGrader(
        _judge("The submission satisfies the rubric.\n\nVERDICT: pass"),
        "judge:fx",
        "Judge whether the report identifies the defect.",
        collect,
    )
    result = grader.grade(tmp_path)
    assert result.passed is True
    assert result.exit_code is None
    assert collected == [tmp_path]

    fail = ModelAssistedGrader(
        _judge("The report misses the defect.\nVERDICT: fail"),
        "judge:fx",
        "Judge whether the report identifies the defect.",
        collect,
    ).grade(tmp_path)
    assert fail.passed is False


def test_model_assisted_grader_without_a_verdict_is_an_unstable_grader(
    tmp_path: Path,
) -> None:
    grader = ModelAssistedGrader(
        _judge("Great work! Looks good to me."),
        "judge:fx",
        "Judge the report.",
        lambda workdir: "submission",
    )
    result = grader.grade(tmp_path)
    # Lesson 8.4: a judge that did not follow the verdict contract has not graded
    # anything; its enthusiasm is not a pass.
    assert result.infrastructure is True
    assert result.passed is None
    assert "VERDICT" in result.output


def test_model_assisted_grader_makes_exactly_one_pinned_call(tmp_path: Path) -> None:
    spy = _SpyJudge(_judge("VERDICT: pass"))
    grader = ModelAssistedGrader(
        spy, "judge:fx", "Judge the submission.", lambda workdir: "the submission"
    )
    grader.grade(tmp_path)
    assert len(spy.requests) == 1
    request = spy.requests[0]
    assert request.messages[0].role == "system"
    assert request.messages[0].content == MODEL_GRADER_SYSTEM_PROMPT
    assert "the submission" in request.messages[-1].content


def test_model_assisted_grader_version_is_the_rubric_hash(tmp_path: Path) -> None:
    a = ModelAssistedGrader(_judge("VERDICT: pass"), "j", "rubric A", lambda p: "s")
    b = ModelAssistedGrader(_judge("VERDICT: pass"), "j", "rubric B", lambda p: "s")
    assert a.version != b.version
    assert a.grade(tmp_path).grader_version == a.version
