"""Repository-instruction discovery (Module 4, Lesson 4.2).

These fail against the scaffolding stubs and pass once discovery is implemented to
the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.repository.discovery import discover_instruction_sources

pytestmark = pytest.mark.student_impl

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "m04" / "repo"


def test_discovers_root_instruction_files_and_architecture_docs() -> None:
    sources = discover_instruction_sources(FIXTURE_REPO)
    assert [(s.path, s.kind) for s in sources] == [
        ("README.md", "readme"),
        ("AGENTS.md", "agents"),
        ("CONTRIBUTING.md", "contributing"),
        ("docs/architecture.md", "doc"),
    ]


def test_missing_sources_are_simply_absent(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# only a readme\n", encoding="utf-8")
    sources = discover_instruction_sources(tmp_path)
    assert [(s.path, s.kind) for s in sources] == [("README.md", "readme")]


def test_docs_are_discovered_recursively_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "docs" / "design").mkdir(parents=True)
    (tmp_path / "docs" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (tmp_path / "docs" / "design" / "adr-1.md").write_text("# adr\n", encoding="utf-8")
    (tmp_path / "docs" / "diagram.txt").write_text("not markdown\n", encoding="utf-8")
    sources = discover_instruction_sources(tmp_path)
    assert [(s.path, s.kind) for s in sources] == [
        ("docs/design/adr-1.md", "doc"),
        ("docs/notes.md", "doc"),
    ]
