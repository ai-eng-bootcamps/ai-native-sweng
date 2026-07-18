"""Read-only ``inspect_diff`` tool (Lesson 3.3: inspect diff).

``inspect_diff`` is a Class 0 (observation-only) tool: it reports every change the run
has made inside the sandbox worktree as one unified diff against the starting revision.
Untracked files are registered with git's intent-to-add first so newly created files
appear in the diff too; ``--full-index`` keeps the output byte-stable across git
versions, which recorded traces rely on. The argument vector is fixed - no model-supplied
value reaches the command line.

Diff inspection is the evidence step: the model uses it to check its own change before
finishing, and the same diff becomes the patch artifact a human approves (Lesson 3.5).

SCAFFOLDING: the contract is supplied; implement ``worktree_diff`` and ``run`` in
Module 3, Lesson 3.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolResult


def worktree_diff(worktree_root: Path) -> str:
    """Return the worktree's unified diff against its starting revision.

    Registers untracked files with intent-to-add so they show up, then diffs with
    ``--full-index`` and no color. Used by this tool and by the write runtime when it
    prepares the patch artifact - the inspected diff and the surfaced patch are the same
    bytes by construction.
    """
    raise NotImplementedError(
        "Module 3, Lesson 3.3: run 'git add --intent-to-add -A .' and then "
        "'git diff --full-index --no-color' in the worktree and return the diff text."
    )


class InspectDiffTool(Tool):
    """Show the run's full unified diff against the sandbox starting revision."""

    name: ClassVar[str] = "inspect_diff"
    description: ClassVar[str] = (
        "Show every change made so far in the sandbox worktree as one unified diff "
        "against the starting revision, including newly created files. Takes no "
        "arguments and never modifies file contents."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 0

    def __init__(self, worktree_root: Path) -> None:
        self._root = worktree_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 3, Lesson 3.3: return worktree_diff(self._root), or '(no changes)' "
            "when the diff is empty."
        )
