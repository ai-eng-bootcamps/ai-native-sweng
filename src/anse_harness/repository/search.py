"""Path search, lexical search, and file relevance scoring (spec 7.3).

Tiers 1 and 2 of the repository-search ladder (Module 4, Lesson 4.3): path and
filename search, then lexical (literal substring) search. Both are deterministic and
dependency-free, which is why the ladder starts here - do not default to a vector
database when a filename match answers the question.

``score_files`` turns lexical evidence into a RANKING: a deterministic relevance score
per file for a set of query terms, weighting a term's appearance in the file's PATH
above its appearances in the file's content (a file named after the concept is a
stronger signal than a file that merely mentions it). The context builder consumes
this ranking to select evidence files.

SCAFFOLDING: the data contracts are supplied; implement ``iter_files``,
``find_paths``, ``lexical_search``, and ``score_files`` in Module 4, Lesson 4.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Weight of one query-term hit in a file's path, relative to one hit in its content.
PATH_HIT_WEIGHT = 3


@dataclass(frozen=True)
class SearchMatch:
    """One matching line: where it is and what it says."""

    path: str
    line: int
    text: str


@dataclass(frozen=True)
class FileScore:
    """One file's deterministic relevance score for a set of query terms."""

    path: str
    score: int


def iter_files(repo_root: Path) -> tuple[str, ...]:
    """List every file under ``repo_root`` as sorted repository-relative POSIX paths.

    Skips anything under ``.git``. The sorted order is what makes every consumer of
    this listing (search, scoring, symbol indexing) deterministic.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.3: walk repo_root recursively; skip paths with a .git "
        "component; return sorted repository-relative POSIX paths of regular files."
    )


def find_paths(repo_root: Path, query: str) -> tuple[str, ...]:
    """Tier 1: return the files whose repository-relative path contains ``query``.

    Matching is case-insensitive; results keep ``iter_files`` order.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.3: filter iter_files(repo_root) to paths containing the "
        "query case-insensitively."
    )


def lexical_search(
    repo_root: Path, query: str, *, max_results: int = 200
) -> tuple[SearchMatch, ...]:
    """Tier 2: return lines containing the literal ``query``, case-insensitively.

    Files that cannot be decoded as UTF-8 are skipped. Results are ordered by
    (path, line) and truncated at ``max_results``.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.3: for each file from iter_files, read UTF-8 text (skip "
        "undecodable files), collect 1-based (path, line, text) for lines containing "
        "the query case-insensitively, stopping at max_results."
    )


def score_files(repo_root: Path, terms: list[str]) -> tuple[FileScore, ...]:
    """Rank files by deterministic relevance to ``terms``.

    A file's score sums, over every term: PATH_HIT_WEIGHT times the term's occurrences
    in the lowercased path, plus its occurrences in the lowercased content (0 for
    undecodable files). Only files with a positive score are returned, ordered by
    score descending, then path ascending - the tiebreak keeps the ranking stable.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.3: compute the weighted term-occurrence score per file, "
        "drop zero scores, and sort by (-score, path)."
    )
