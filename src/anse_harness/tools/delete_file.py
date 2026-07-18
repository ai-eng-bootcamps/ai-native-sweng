"""Narrow ``delete_file`` edit tool, approval-required (Lesson 3.3: delete with approval).

``delete_file`` is a Class 2 (local consequential change) tool: deleting is the one edit
whose content cannot be inspected afterward, so it never happens on the agent's own
authority. Every request is routed through the ``ApprovalGate`` (Lesson 3.5) as an
``ApprovalRequest``; only an approved decision deletes, and a rejection comes back as a
not-ok observation the model must respect. Even an approved deletion is confined to the
sandbox worktree and remains reversible by rollback.

SCAFFOLDING: the contract (name, description, schema, side-effect class) is supplied;
implement ``run`` in Module 3, Lessons 3.3 and 3.5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.approvals.gate import ApprovalGate
from anse_harness.tools.base import Tool, ToolResult


class DeleteFileTool(Tool):
    """Delete one file inside the sandbox worktree, subject to explicit approval."""

    name: ClassVar[str] = "delete_file"
    description: ClassVar[str] = (
        "Request deletion of a file inside the sandbox worktree. Deletion is a "
        "consequential action: every request goes to the approval gate, and the file is "
        "removed only when the deletion is approved. Paths are relative to the worktree "
        "root; deletions outside the worktree or into .git are rejected."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Worktree-relative path of the file to delete.",
            },
            "reason": {
                "type": "string",
                "description": "Why the file should be deleted; shown to the approver.",
            },
        },
        "required": ["path", "reason"],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 2

    def __init__(self, worktree_root: Path, gate: ApprovalGate) -> None:
        self._root = worktree_root.resolve()
        self._gate = gate

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 3, Lessons 3.3/3.5: validate the path and reason; route an "
            "ApprovalRequest (action delete_file, class-2 risk, the affected path) "
            "through the gate; delete only on APPROVED, and report any other decision "
            "as a not-ok observation."
        )
