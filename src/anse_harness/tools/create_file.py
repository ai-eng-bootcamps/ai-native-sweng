"""Narrow ``create_file`` edit tool (Lesson 3.3: safe edit tools).

``create_file`` is a Class 1 (local reversible change) tool: it creates one new UTF-8
text file inside the sandbox worktree. It refuses to overwrite - creating is creating,
and replacing existing content belongs to ``replace_text``, so a wrong-file request
cannot silently destroy anything. Paths and content are bounded by the shared guards in
``tools/write_guards.py``; the write lands only inside the worktree, so it is fully
reversible by rollback.

SCAFFOLDING: the contract (name, description, schema, side-effect class) is supplied;
implement ``run`` in Module 3, Lesson 3.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolResult


class CreateFileTool(Tool):
    """Create one new UTF-8 text file inside the sandbox worktree."""

    name: ClassVar[str] = "create_file"
    description: ClassVar[str] = (
        "Create a new UTF-8 text file inside the sandbox worktree with the given content. "
        "Paths are relative to the worktree root; writes outside the worktree, into .git, "
        "or over an existing file are rejected. Edits are size-bounded."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Worktree-relative path of the file to create.",
            },
            "content": {
                "type": "string",
                "description": "Full UTF-8 content of the new file.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 1

    def __init__(self, worktree_root: Path) -> None:
        self._root = worktree_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 3, Lesson 3.3: validate the content (string, size-bounded) and the "
            "path (validate_edit_path); refuse to overwrite an existing file as a not-ok "
            "observation; otherwise create parent directories inside the worktree, write "
            "the file, and report the created path and size."
        )
