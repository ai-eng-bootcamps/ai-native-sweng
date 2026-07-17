"""Read-only ``inspect_git_status`` tool (spec Module 2, Lesson 2.3: read-only tools).

``inspect_git_status`` is a Class 0 (observation-only) tool: it reports the Git
working-tree status of the repository under investigation by running
``git status --porcelain`` and returning its output (empty when the tree is clean). The
argument vector is fixed and no model-supplied value ever reaches the command line, so
there is nothing to inject; the command is read-only and never modifies the repository.

SCAFFOLDING: the contract (name, description, schema, side-effect class) is supplied;
implement ``run`` in Module 2, Lesson 2.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolResult


class InspectGitStatusTool(Tool):
    """Report the repository's Git working-tree status (porcelain)."""

    name: ClassVar[str] = "inspect_git_status"
    description: ClassVar[str] = (
        "Report the Git working-tree status of the repository under investigation as porcelain "
        "output (empty when the tree is clean). Runs 'git status --porcelain' read-only and "
        "never modifies the repository."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 0

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 2, Lesson 2.3: run 'git status --porcelain' with cwd=self._root (a fixed "
            "argv, no shell), and return stdout as a ToolResult; report a non-zero exit as "
            "ok=False."
        )
