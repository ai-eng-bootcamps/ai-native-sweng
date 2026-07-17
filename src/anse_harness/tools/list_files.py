"""Read-only ``list_files`` tool (spec Module 2, Lesson 2.3: read-only tools).

``list_files`` is a Class 0 (observation-only) tool: it lists the repository-relative
paths of the files under a directory in the repository under investigation, and never
writes. The security boundary is the repository root - the tool refuses any path that
resolves outside it, exactly like ``read_file``. The ``.git`` directory is skipped so a
listing describes source, not version-control internals.

SCAFFOLDING: the contract (name, description, schema, side-effect class) is supplied;
implement ``run`` in Module 2, Lesson 2.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolResult


class ListFilesTool(Tool):
    """List repository-relative file paths under a directory, sorted."""

    name: ClassVar[str] = "list_files"
    description: ClassVar[str] = (
        "List repository-relative file paths under a directory in the repository under "
        "investigation, one per line, sorted. Paths are relative to the repository root; "
        "listings outside the repository are rejected. This tool never modifies the repository."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repository-relative directory to list; defaults to the root.",
            }
        },
        "required": [],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 0

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 2, Lesson 2.3: resolve 'path' (default '.') inside self._root, reject "
            "escapes with PathValidationError, then return the sorted repository-relative "
            "paths of the files under it (skip .git) as a newline-joined ToolResult."
        )
