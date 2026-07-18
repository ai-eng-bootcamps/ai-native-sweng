"""Test discovery and test-to-subject mapping for Go repositories (spec 7.3).

Tier 6 of the repository-search ladder (Module 4, Lesson 4.3): knowing WHICH tests
exercise a file is context an implementer and a reviewer both need - the implementer
to keep them passing, the reviewer to judge whether the change is covered. Go makes
the association conventional: ``x_test.go`` sits next to ``x.go`` in the same
package, and every test function is named ``Test*``.

SCAFFOLDING: the data contract is supplied; implement ``map_tests`` in Module 4,
Lesson 4.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestMapping:
    """One test file, the source file it conventionally covers, and its test names."""

    test_file: str
    #: The sibling ``x.go`` for ``x_test.go``, or ``None`` when no such file exists.
    subject_file: str | None
    #: ``Test*`` function names in the test file, in declaration order.
    test_names: tuple[str, ...]


def map_tests(repo_root: Path) -> tuple[TestMapping, ...]:
    """Map every ``*_test.go`` file to its conventional subject and its test functions.

    Results are ordered by test file path so the mapping is deterministic.
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.3: for each *_test.go file (sorted), the subject is the "
        "sibling file with _test stripped when it exists; the test names are the "
        "file's top-level 'func Test*' declarations in line order (the symbol index "
        "already finds those)."
    )
