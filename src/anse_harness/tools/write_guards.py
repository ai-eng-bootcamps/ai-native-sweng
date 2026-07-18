"""Shared guards for the narrow edit tools (Lesson 3.3: path and size validation).

Every edit tool validates the same two bounds before it touches anything:

* **Path validation.** The requested path must resolve inside the sandbox worktree
  (rejecting traversal, absolute escapes, and symlinks pointing out - exactly the
  ``read_file`` boundary from Module 2) and must not reach into ``.git``, because edits
  to version-control internals corrupt the workspace rather than change the code.
  Violations raise: an escape attempt is a contract violation that fails the run, not an
  observation the model may retry its way around.
* **Size validation.** A single edit is bounded to ``MAX_EDIT_BYTES`` of UTF-8 content.
  Narrow tools are bounded tools (architecture-reference.md, Tool Design Principles);
  an edit too large to review is an edit too large to make.

SCAFFOLDING: the bound and the error type are supplied; implement both guards in
Module 3, Lesson 3.3.
"""

from __future__ import annotations

from pathlib import Path

from anse_harness.tools.base import ToolError

#: Upper bound on the UTF-8 content of one edit (file body or replacement text).
MAX_EDIT_BYTES = 64 * 1024


class EditSizeError(ToolError):
    """An edit's content exceeded the per-edit size bound."""


def validate_edit_path(root: Path, raw: object) -> Path:
    """Resolve a model-supplied path against the worktree root, or raise.

    Returns the resolved absolute path. Raises ``PathValidationError`` for a missing or
    empty argument, a path that resolves outside ``root``, or a path inside ``.git``.
    ``root`` must already be resolved.
    """
    raise NotImplementedError(
        "Module 3, Lesson 3.3: require a non-empty string, resolve it against root, "
        "reject resolutions outside root and any path whose parts include '.git' with "
        "PathValidationError, and return the resolved path."
    )


def validate_edit_size(text: str, what: str) -> None:
    """Raise ``EditSizeError`` when ``text`` exceeds the per-edit size bound."""
    raise NotImplementedError(
        "Module 3, Lesson 3.3: measure the UTF-8 size of text and raise EditSizeError "
        "(naming what and the bound) when it exceeds MAX_EDIT_BYTES."
    )
