"""Repository-instruction and architecture-document discovery (spec 7.3).

A repository carries instructions for the people (and agents) that work on it: the
README, contributor guides, AGENTS-style instruction files, and the documents under
``docs/``. Before an agent selects code evidence it must know these exist - a context
packet that omits the repository's own rules produces work that violates them (Module
4, Lesson 4.2).

Discovery is deliberately convention-based and deterministic: the three well-known
root files, then every Markdown file under ``docs/``. What each source is TRUSTED to
say is a separate question answered by ``instructions/precedence.py``.

SCAFFOLDING: the data contract is supplied; implement ``discover_instruction_sources``
in Module 4, Lesson 4.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Root-level instruction files, in the fixed order they are reported.
ROOT_SOURCES: tuple[tuple[str, str], ...] = (
    ("README.md", "readme"),
    ("AGENTS.md", "agents"),
    ("CONTRIBUTING.md", "contributing"),
)

#: Directory whose Markdown files are reported as architecture documents.
DOCS_DIR = "docs"


@dataclass(frozen=True)
class InstructionSource:
    """One discovered instruction or architecture document."""

    #: Repository-relative POSIX path.
    path: str
    #: One of "readme", "agents", "contributing", or "doc".
    kind: str


def discover_instruction_sources(repo_root: Path) -> tuple[InstructionSource, ...]:
    """Discover the repository's instruction files and architecture documents.

    Returns the root files that exist, in ``ROOT_SOURCES`` order, followed by every
    ``*.md`` under ``docs/`` in sorted path order (kind ``"doc"``). The order is fixed
    so discovery is deterministic across machines.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.2: report each ROOT_SOURCES file that exists at the "
        "repository root, then every .md file under docs/ (recursive, sorted, "
        "repository-relative POSIX paths) with kind 'doc'."
    )
