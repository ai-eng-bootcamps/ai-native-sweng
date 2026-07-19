"""Graders: the pass/fail oracles of an evaluation, behind one interface (Lesson 8.3).

A grader answers exactly one question about one attempt: did the produced change
accomplish the task? Graders are heterogeneous inside - deterministic test suites,
behavioral assertions, diff and static checks, mutation analysis, rubric-driven model
judgment - but uniform outside: every grader is invoked against a working copy that has
the attempt's patch applied, and returns a ``GraderResult``.

Two implementations matter in this course, and they are NOT the same thing:

* the student-side deterministic grader (``VisibleValidationGrader``) runs the
  manifest's ``visible_validation`` commands - the checks the task statement publishes;
* command graders (``CommandGrader``) run an external grader program under the course
  exit-code contract. The INSTRUCTOR-side hidden graders are command graders over
  scripts students never receive; your own project graders use the same contract.

The exit-code contract (uniform across all course graders): exit 0 = the attempt
passes, exit 1 = the attempt fails, any other exit (2 is the conventional usage/
environment error) = the GRADER could not run - an infrastructure error that must never
be scored as a task failure, and never as a pass.

Grader VERSIONING: every result records the grader's identity and a content-hash
version. A grader that changes mid-evaluation silently changes what "pass" means; the
recorded version makes that visible and comparable across reports.

The model-assisted grader (``ModelAssistedGrader``) is an INTERFACE over the model
adapter: scripted by default (zero live cost), and honest about instability - a judge
response without a parseable verdict is an infrastructure error, not a grade
(Lesson 8.4: unstable graders).

SCAFFOLDING: the result contract, the exit-code mapping, and the command grader are
supplied; implement ``VisibleValidationGrader.grade`` and ``ModelAssistedGrader.grade``
in Module 8, Lessons 8.3-8.4.
"""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from anse_harness.evaluation.dataset import TaskManifest
from anse_harness.models import ModelAdapter

#: The grader exit-code contract: pass, fail, and the conventional infrastructure code.
GRADE_PASS = 0
GRADE_FAIL = 1
GRADE_INFRASTRUCTURE = 2

#: Pinned system text for model-assisted grading. Building this per call would change
#: recorded requests and break replay - the Module 2 pinning discipline.
MODEL_GRADER_SYSTEM_PROMPT = (
    "You are a grading assistant for an engineering evaluation. Judge ONLY whether the "
    "submission satisfies the grading instruction; do not reward style, length, or "
    "confidence. End your reply with a single line of the form 'VERDICT: pass' or "
    "'VERDICT: fail'. If the submission cannot be judged from the material given, "
    "explain why and end with 'VERDICT: fail'."
)

#: The line prefix the model-assisted grader requires in the judge's reply.
VERDICT_PREFIX = "VERDICT:"


def grader_version_hash(content: bytes) -> str:
    """Content-hash grader version: the first 12 hex digits of SHA-256.

    Hash the material that DEFINES the grader's judgment (a script's bytes, a command
    line, a rubric instruction); two graders with the same version make the same call.
    """
    return hashlib.sha256(content).hexdigest()[:12]


@dataclass(frozen=True)
class GraderResult:
    """One grader's answer for one attempt, with the identity that produced it.

    ``passed`` is ``None`` exactly when ``infrastructure`` is True: a grader that could
    not run has NO opinion, and downstream metrics must exclude the run from pass-rate
    denominators rather than counting it either way.
    """

    grader_id: str
    grader_version: str
    passed: bool | None
    exit_code: int | None
    output: str
    infrastructure: bool

    def __post_init__(self) -> None:
        if self.infrastructure != (self.passed is None):
            raise ValueError("passed must be None exactly when infrastructure is True")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for run records and trace-adjacent artifacts."""
        return {
            "grader_id": self.grader_id,
            "grader_version": self.grader_version,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "output": self.output,
            "infrastructure": self.infrastructure,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> GraderResult:
        """Deserialize one payload back into a GraderResult."""
        return cls(
            grader_id=str(data["grader_id"]),
            grader_version=str(data["grader_version"]),
            passed=None if data["passed"] is None else bool(data["passed"]),
            exit_code=None if data["exit_code"] is None else int(data["exit_code"]),
            output=str(data["output"]),
            infrastructure=bool(data["infrastructure"]),
        )


def result_from_exit_code(
    grader_id: str, grader_version: str, exit_code: int, output: str
) -> GraderResult:
    """Map one exit code to a GraderResult under the course contract.

    0 is a pass, 1 is a fail, and EVERY other code is an infrastructure error: an
    unexpected exit (a crash, a missing toolchain, exit 2 usage errors) is the
    grader failing, not the attempt.
    """
    if exit_code == GRADE_PASS:
        return GraderResult(grader_id, grader_version, True, exit_code, output, False)
    if exit_code == GRADE_FAIL:
        return GraderResult(grader_id, grader_version, False, exit_code, output, False)
    return GraderResult(grader_id, grader_version, None, exit_code, output, True)


def infrastructure_result(grader_id: str, grader_version: str, detail: str) -> GraderResult:
    """A GraderResult for a grader that could not run at all."""
    return GraderResult(grader_id, grader_version, None, None, detail, True)


class Grader(Protocol):
    """The single external shape every grader presents to the evaluation runner."""

    @property
    def grader_id(self) -> str:
        """Stable identifier recorded on every result."""
        ...

    @property
    def version(self) -> str:
        """Content-hash version recorded on every result."""
        ...

    def grade(self, workdir: Path) -> GraderResult:
        """Judge the working copy at ``workdir`` (attempt patch already applied)."""
        ...


class CommandGrader:
    """An external grader program under the exit-code contract, run from the workdir root.

    ``script`` names the grader program; ``interpreter`` prefixes the argv (for example
    ``(sys.executable,)`` for a Python grader or ``("bash",)`` for a shell one). The
    version is the content hash of the script bytes, so editing the grader changes the
    recorded version. The instructor-side hidden graders are exactly this shape over
    scripts that are never distributed with the course repository.
    """

    def __init__(
        self,
        grader_id: str,
        script: Path,
        *,
        interpreter: tuple[str, ...] = (),
        args: tuple[str, ...] = (),
        timeout_seconds: float = 300.0,
    ) -> None:
        self.grader_id = grader_id
        # Resolved at init: the grader runs with the WORKDIR as its cwd, so a
        # relative script path would resolve against the wrong root.
        self.script = script.resolve()
        self.interpreter = interpreter
        self.args = args
        self.timeout_seconds = timeout_seconds
        self.version = grader_version_hash(script.read_bytes())

    def grade(self, workdir: Path) -> GraderResult:
        """Run the grader program with ``workdir`` as its working directory."""
        argv = [*self.interpreter, str(self.script), *self.args]
        try:
            proc = subprocess.run(
                argv,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return infrastructure_result(
                self.grader_id, self.version, f"grader could not run: {exc}"
            )
        output = proc.stdout + proc.stderr
        return result_from_exit_code(self.grader_id, self.version, proc.returncode, output)


class VisibleValidationGrader:
    """The student-side deterministic grader: the manifest's own published checks.

    This is the oracle a student's runner is allowed to use for course tasks: the
    ``visible_validation`` command entries of the task manifest, run in order from the
    working-copy root. Artifact-kind entries describe human review, not commands - they
    are reported, never executed. Hidden graders judge the same working copy on the
    instructor side; nothing here invokes them.
    """

    def __init__(self, manifest: TaskManifest, *, timeout_seconds: float = 300.0) -> None:
        self.manifest = manifest
        self.grader_id = f"visible:{manifest.task_id}"
        self.timeout_seconds = timeout_seconds
        self.version = grader_version_hash("\n".join(manifest.visible_commands).encode("utf-8"))

    def grade(self, workdir: Path) -> GraderResult:
        """Run every command-kind visible check; all must pass.

        Commands are split with ``shlex.split`` and run from ``workdir``. The result is
        a pass when every command exits 0 and a fail on the first non-zero exit; a
        command that cannot be launched at all is an infrastructure error. The output
        names each check and its outcome, and lists artifact-kind entries as
        "human review:" lines.
        """
        raise NotImplementedError(
            "Module 8, Lesson 8.3: iterate manifest.visible_validation in order; for "
            "'command' entries run shlex.split(command) from workdir (capture output, "
            "honor timeout_seconds) - first non-zero exit makes the result a fail "
            "(exit_code = that command's exit), all zero makes it a pass (exit_code 0); "
            "OSError/TimeoutExpired makes it infrastructure_result; for 'artifact' "
            "entries append 'human review: <description>' to the output instead of "
            "executing anything."
        )


class ModelAssistedGrader:
    """A rubric-driven model judge behind the same grader interface (Lesson 8.4).

    Adapter-shaped: with a scripted or replay adapter the judge costs nothing and is
    deterministic; with a live adapter it inherits every judge failure mode the lesson
    catalogues. ``collect`` gathers the submission text to judge from the working copy
    (a report file, a rendered diff) - the grader itself never guesses where to look.
    The version is the content hash of the grading instruction: change the rubric,
    change the version.
    """

    def __init__(
        self,
        adapter: ModelAdapter,
        grader_id: str,
        instruction: str,
        collect: Callable[[Path], str],
    ) -> None:
        self.adapter = adapter
        self.grader_id = grader_id
        self.instruction = instruction
        self.collect = collect
        self.version = grader_version_hash(instruction.encode("utf-8"))

    def grade(self, workdir: Path) -> GraderResult:
        """Ask the judge for a verdict on the collected submission.

        Exactly one model call. The reply's LAST non-empty line must be
        ``VERDICT: pass`` or ``VERDICT: fail`` (case-insensitive on the verdict word);
        any other shape is an unstable-grader infrastructure error - a judge that did
        not follow the verdict contract has not graded anything, and treating its prose
        as a grade would be exactly the failure mode Lesson 8.4 warns about.
        """
        raise NotImplementedError(
            "Module 8, Lesson 8.4: build a ModelRequest with MODEL_GRADER_SYSTEM_PROMPT "
            "as the system message and one user message containing the instruction and "
            "collect(workdir); call adapter.complete once; take the reply's last "
            "non-empty line - if it is VERDICT_PREFIX followed by 'pass' or 'fail' "
            "(case-insensitive), return a GraderResult with passed True/False, exit_code "
            "None, and the full reply text as output; otherwise return "
            "infrastructure_result explaining the missing verdict."
        )


def _shlex_join(parts: list[str]) -> str:
    """Deterministic rendering of an argv for grader output lines."""
    return " ".join(shlex.quote(part) for part in parts)
