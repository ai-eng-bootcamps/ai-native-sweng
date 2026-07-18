"""Narrow ``replace_text`` edit tool (Lesson 3.3: safe edit tools).

``replace_text`` is a Class 1 (local reversible change) tool: it replaces one exactly-
matching region of text in one existing UTF-8 file inside the sandbox worktree. The
uniqueness rule is the tool's teeth: ``old_text`` must occur EXACTLY ONCE in the file.
Zero occurrences means the model's mental picture of the file is stale; more than one
means the edit is ambiguous - both come back as not-ok observations the model must
resolve by reading the file again, instead of the tool guessing which occurrence was
meant. Paths and content are bounded by the shared guards in ``tools/write_guards.py``.

SCAFFOLDING: the contract (name, description, schema, side-effect class) is supplied;
implement ``run`` in Module 3, Lesson 3.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolResult


class ReplaceTextTool(Tool):
    """Replace one uniquely-matching text region in a file inside the sandbox worktree."""

    name: ClassVar[str] = "replace_text"
    description: ClassVar[str] = (
        "Replace text in a UTF-8 file inside the sandbox worktree. old_text must occur "
        "exactly once in the file; zero or multiple occurrences are rejected so the edit "
        "is never ambiguous. Paths are relative to the worktree root; edits outside the "
        "worktree or into .git are rejected. Edits are size-bounded."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Worktree-relative path of the file to edit.",
            },
            "old_text": {
                "type": "string",
                "description": "Exact text to replace; must occur exactly once in the file.",
            },
            "new_text": {
                "type": "string",
                "description": "Replacement text.",
            },
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 1

    def __init__(self, worktree_root: Path) -> None:
        self._root = worktree_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 3, Lesson 3.3: validate the arguments and the path; return not-ok "
            "observations for a missing file, zero occurrences, or multiple occurrences "
            "of old_text; otherwise replace the single occurrence, size-check the "
            "resulting file, write it back, and report the edit."
        )
