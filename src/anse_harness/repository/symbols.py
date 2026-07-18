"""Deterministic declaration-level symbol indexing for Go sources (spec 7.3).

Tier 3 of the repository-search ladder (Module 4, Lesson 4.3): after filenames and
lexical search, symbol search answers "where is this DEFINED" instead of "where does
this string appear". The course indexes at declaration level by scanning lines for the
three Go declaration forms that matter for navigation - ``func``, methods (``func``
with a receiver), and ``type`` - which is deterministic, dependency-free, and replay
safe. Language-server data (tier 4) gives richer answers but needs a running server
per language; the lessons discuss it, the harness does not require it.

SCAFFOLDING: the data contract is supplied; implement ``index_symbols`` in Module 4,
Lesson 4.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Symbol:
    """One declaration: its name, kind (func/method/type), location, and receiver."""

    name: str
    #: One of "func", "method", or "type".
    kind: str
    #: Repository-relative POSIX path of the defining file.
    file: str
    #: 1-based line number of the declaration.
    line: int
    #: Receiver type name for methods; ``None`` for funcs and types.
    receiver: str | None = None


def index_symbols(repo_root: Path) -> tuple[Symbol, ...]:
    """Index every top-level Go declaration under ``repo_root``.

    Scans each ``.go`` file line by line for ``func Name(``, ``func (recv Type) Name(``,
    and ``type Name`` declarations. Results are ordered by (file, line) so the index is
    deterministic across machines.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.3: for each .go file (in sorted path order, skipping .git), "
        "match each line against the three Go declaration forms; record a Symbol with "
        "the 1-based line number, and the receiver type (stripped of '*') for methods."
    )
