"""Package-level dependency evidence from Go import declarations (spec 7.3).

Tier 5 of the repository-search ladder (Module 4, Lesson 4.3): once the relevant files
are known, their package's imports and dependents say what else the change can touch.
A file's package importing ``internal/booking`` is EVIDENCE that booking's contracts
constrain it; a package imported by three others is evidence that changing it has
three consumers. The graph is built by scanning ``import`` declarations - no build
system, no toolchain, deterministic on every machine.

Only imports inside the repository's own module (the ``module`` line of ``go.mod``)
become edges: the graph answers questions about THIS repository, not about the
standard library.

SCAFFOLDING: the data contract is supplied; implement ``build_import_graph`` in
Module 4, Lesson 4.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ImportGraph:
    """Package-level import edges: package directory -> imported package directories."""

    #: Maps each package directory (repository-relative POSIX path) to the sorted
    #: repository-internal package directories it imports.
    imports: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def imports_of(self, package: str) -> tuple[str, ...]:
        """The repository-internal packages ``package`` imports."""
        return self.imports.get(package, ())

    def dependents_of(self, package: str) -> tuple[str, ...]:
        """The repository-internal packages that import ``package``, sorted."""
        return tuple(sorted(pkg for pkg, deps in self.imports.items() if package in deps))


def build_import_graph(repo_root: Path) -> ImportGraph:
    """Build the repository-internal import graph from the ``.go`` files.

    The module path comes from the ``module`` line of ``go.mod``; an import is
    internal when it starts with that path, and its package directory is the
    remainder. Files in the same directory belong to one package node. Without a
    ``go.mod`` the graph has nodes but no edges (nothing can be identified as
    internal).
    """
    raise NotImplementedError(
        "Module 4, Lesson 4.3: read the module path from go.mod; for each .go file, "
        "parse its import declarations (single-line and block form), keep imports "
        "prefixed by the module path, and record them as sorted edges from the file's "
        "package directory to the imported package directories."
    )
