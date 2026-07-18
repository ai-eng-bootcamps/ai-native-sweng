"""Policy-gated ``run_validation_command`` tool (Lesson 3.4: command policies).

The write agent's command surface. The model supplies a command as an argv list (no
shell, so shell metacharacters cannot inject); the deterministic
``CommandPolicyEngine`` classifies it and only an ``allow`` decision executes - the
read-only and validation classes. Everything else (mutating, destructive, networked,
prohibited, unclassified) comes back unexecuted as a not-ok observation carrying the
full policy decision, so the denial is visible in the trace and the model can adapt.

This is Module 2's ``run_read_only_command`` grown into a policy engine: the allowlist
is no longer a flat set but a classification with per-class decisions, and it is still
made entirely outside the model. Commands run inside the sandbox worktree only.

SCAFFOLDING: the contract is supplied; implement ``run`` in Module 3, Lesson 3.4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.policy.commands import CommandPolicyEngine
from anse_harness.tools.base import Tool, ToolResult


class RunValidationCommandTool(Tool):
    """Run one policy-allowed command inside the sandbox worktree; deny the rest."""

    name: ClassVar[str] = "run_validation_command"
    description: ClassVar[str] = (
        "Run one read-only or validation command inside the sandbox worktree and return "
        "its output. The command is an argv list (no shell). A deterministic command "
        "policy classifies every request; only allow-class commands execute, and every "
        "other class is returned as a policy decision without executing."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command as an argv list, e.g. ['go', 'test', './...'].",
            }
        },
        "required": ["command"],
        "additionalProperties": False,
    }
    #: Validation runs may write build artifacts inside the worktree (Lesson 3.4:
    #: side-effect class 0 to 1); the class records the upper bound.
    side_effect_class: ClassVar[int] = 1

    def __init__(self, worktree_root: Path, policy: CommandPolicyEngine) -> None:
        self._root = worktree_root.resolve()
        self._policy = policy

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 3, Lesson 3.4: require a non-empty argv list; evaluate it with the "
            "policy engine and return any non-allow decision as a not-ok observation "
            "carrying the rendered decision; run an allowed command in the worktree "
            "(no shell, bounded timeout) and return its output."
        )
