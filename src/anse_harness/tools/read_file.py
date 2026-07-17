"""Read-only ``read_file`` tool with path validation (spec Module 2: tools validate paths).

``read_file`` is a Class 0 (observation-only) tool: it reads a UTF-8 text file
from inside the repository under investigation and never writes. The security
boundary is the repository root - the tool must refuse any path that resolves
outside it (path traversal such as ``../../etc/passwd``, or an absolute path
like ``/etc/passwd``). Resolution follows symlinks, so a symlink that points out
of the root is rejected too.

SCAFFOLDING: implement ``run`` in Module 2, Lesson 2.1. The contract (name,
description, schema, side-effect class) is supplied; the path validation and the
read are yours to write.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolError, ToolResult


class PathValidationError(ToolError):
    """A requested path escaped the repository root or was otherwise invalid."""


class ReadFileTool(Tool):
    """Read a UTF-8 text file from the repository under investigation."""

    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = (
        "Read a UTF-8 text file from the repository under investigation and return "
        "its contents. Paths are relative to the repository root; reads outside the "
        "repository are rejected. This tool never modifies the repository."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repository-relative path to the file to read.",
            }
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 0

    def __init__(self, repo_root: Path) -> None:
        # Resolve the root once so every request is validated against a canonical,
        # symlink-free absolute path.
        self._root = repo_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 2, Lesson 2.1: validate 'path' resolves inside self._root "
            "(reject traversal and absolute escapes with PathValidationError), then "
            "return the file's contents as a ToolResult."
        )
