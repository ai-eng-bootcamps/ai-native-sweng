"""Read-only ``search_text`` tool (spec Module 2, Lesson 2.3: read-only tools).

``search_text`` is a Class 0 (observation-only) grep-like tool: it looks for a literal
substring across the UTF-8 text files under a directory in the repository under
investigation and returns the matching lines as ``path:line: text``, sorted. It never
writes. The query is a literal substring, not a regular expression, so the tool is
deterministic and has no pathological-input failure mode. The security boundary is the
repository root, exactly as for ``read_file``.

SCAFFOLDING: the contract (name, description, schema, side-effect class) is supplied;
implement ``run`` in Module 2, Lesson 2.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from anse_harness.tools.base import Tool, ToolResult


class SearchTextTool(Tool):
    """Search for a literal substring across the repository's text files."""

    name: ClassVar[str] = "search_text"
    description: ClassVar[str] = (
        "Search for a literal substring across UTF-8 text files under a directory in the "
        "repository under investigation, returning matching lines as 'path:line: text', "
        "sorted. Paths are relative to the repository root; searches outside the repository "
        "are rejected. This tool never modifies the repository."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Literal substring to search for."},
            "path": {
                "type": "string",
                "description": "Repository-relative directory to search; defaults to the root.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    side_effect_class: ClassVar[int] = 0

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root.resolve()

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(
            "Module 2, Lesson 2.3: validate a non-empty 'query' (raise ToolError otherwise) and "
            "resolve 'path' (default '.') inside self._root; scan the UTF-8 text files under it "
            "for lines containing the literal query and return 'path:line: text' matches, sorted."
        )
