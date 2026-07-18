"""Validation pipeline: deterministic verification of a proposed change (spec 7.11; Lesson 3.5).

Before a change is trusted, a fixed list of checks - the target's own toolchain:
formatting, compilation, tests - runs against the sandbox worktree and produces a
structured report. The worker is not allowed to claim success merely because it says the
task is complete (spec 7.11): the report, not the model's prose, is what the approval
boundary acts on.

The pipeline is itself policy-governed: every check's command is evaluated by the
``CommandPolicyEngine`` first, and a check whose command the policy does not allow FAILS
without executing. A validation pipeline that could be pointed at an arbitrary command
would be the unrestricted shell in disguise.

SCAFFOLDING: the check and report contracts are supplied; implement
``ValidationPipeline.run`` in Module 3, Lesson 3.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anse_harness.policy.commands import CommandPolicyEngine


@dataclass(frozen=True)
class ValidationCheck:
    """One named check: a policy-allowed command run inside the worktree."""

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    """The structured outcome of one check (spec 7.11: results are structured)."""

    name: str
    command: tuple[str, ...]
    ok: bool
    #: Process exit code; None when the check did not execute (policy denial, timeout).
    exit_code: int | None
    output: str

    def to_payload(self) -> dict[str, Any]:
        """Serialize for trace payloads (validation_completed)."""
        return {
            "name": self.name,
            "command": list(self.command),
            "ok": self.ok,
            "exit_code": self.exit_code,
            "output": self.output,
        }


@dataclass(frozen=True)
class ValidationReport:
    """All check results for one run; the evidence the approval boundary acts on."""

    results: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        """True only when every check ran and passed."""
        return all(result.ok for result in self.results)

    def to_payload(self) -> dict[str, Any]:
        """Serialize for trace payloads (validation_completed)."""
        return {"ok": self.ok, "checks": [result.to_payload() for result in self.results]}


class ValidationPipeline:
    """Runs the configured checks in order against one sandbox worktree."""

    def __init__(
        self,
        worktree_root: Path,
        checks: list[ValidationCheck],
        policy: CommandPolicyEngine,
        *,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._root = worktree_root.resolve()
        self._checks = list(checks)
        self._policy = policy
        self._timeout = timeout_seconds

    @property
    def checks(self) -> tuple[ValidationCheck, ...]:
        """The configured checks, in run order (recorded by validation_started)."""
        return tuple(self._checks)

    def run(self) -> ValidationReport:
        """Run every check and return the structured report.

        Checks always all run (a later check may fail for a different reason worth
        seeing), but any single failure fails the report. A policy-denied check fails
        WITHOUT executing, with the policy decision as its output.
        """
        raise NotImplementedError(
            "Module 3, Lesson 3.5: for each check, evaluate its command with the policy "
            "engine and fail it without executing on any non-allow decision; otherwise "
            "run it in the worktree (no shell, bounded timeout, failure on nonzero "
            "exit or timeout) and collect every CheckResult into a ValidationReport."
        )
