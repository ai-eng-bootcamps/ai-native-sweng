"""Policy-gated ``run_read_only_command`` tool (spec Module 2, Lesson 2.3).

``run_read_only_command`` is a Class 0 (observation-only) tool guarded by an explicit
allowlist. The model supplies a command as an argv list (no shell, so shell
metacharacters cannot inject); the tool consults a fixed allowlist of read-only commands
and *denies everything else* as a policy decision made outside the model. A denied
command is returned as a not-ok observation (``ok=False``) so the model can adapt, rather
than raised, because a denial is a normal event in a bounded runtime, not a contract
violation.

The allowlist here is deliberately tiny and read-only (a handful of Git query
subcommands). It is the mechanism, not the catalogue: widening it is a policy decision,
made here in code, never by the model.

SCAFFOLDING: the contract (name, description, schema, side-effect class) and the allowlist
are supplied; implement ``run`` in Module 2, Lesson 2.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolResult

#: Read-only allowlist: executable -> permitted subcommands. Everything else is denied.
ALLOWLIST: dict[str, frozenset[str]] = {
    "git": frozenset(
        {"status", "log", "diff", "show", "ls-files", "rev-parse", "cat-file", "blame", "shortlog"}
    ),
}


class RunReadOnlyCommandTool(Tool):
    """Run one command from a fixed read-only allowlist; deny everything else."""

    name: ClassVar[str] = "run_read_only_command"
    description: ClassVar[str] = (
        "Run one command from a fixed read-only allowlist in the repository under "
        "investigation and return its output. The command is an argv list (no shell). Only "
        "observation-only commands on the allowlist are permitted; every other command is "
        "denied. This tool never modifies the repository."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command as an argv list, e.g. ['git', 'status', '--porcelain'].",
            }
        },
        "required": ["command"],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 0

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 2, Lesson 2.3: require 'command' to be a non-empty argv list (raise ToolError "
            "otherwise); deny anything not on ALLOWLIST as ok=False (policy decision); run an "
            "allowed command with cwd=self._root (no shell) and return its output."
        )
