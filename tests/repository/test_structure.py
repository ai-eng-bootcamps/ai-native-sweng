"""Symbol indexing, test mapping, and dependency evidence (Module 4, Lesson 4.3).

These fail against the scaffolding stubs and pass once the structural search tiers
are implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.repository.dependencies import build_import_graph
from anse_harness.repository.symbols import Symbol, index_symbols
from anse_harness.repository.test_map import map_tests

pytestmark = pytest.mark.student_impl

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "m04" / "repo"


def test_symbol_index_finds_types_funcs_and_methods() -> None:
    symbols = index_symbols(FIXTURE_REPO)
    assert Symbol("Hold", "type", "internal/booking/hold.go", 10) in symbols
    assert Symbol("ExpiresAt", "method", "internal/booking/hold.go", 16, "Hold") in symbols
    assert Symbol("Expired", "method", "internal/booking/hold.go", 21, "Hold") in symbols
    assert any(s.name == "holdActive" and s.kind == "func" for s in symbols)


def test_symbol_index_is_ordered_by_file_then_line() -> None:
    symbols = index_symbols(FIXTURE_REPO)
    keys = [(s.file, s.line) for s in symbols]
    assert keys == sorted(keys)


def test_symbol_index_strips_pointer_receivers(tmp_path: Path) -> None:
    (tmp_path / "x.go").write_text(
        "package x\n\nfunc (s *Store) Close() error {\n\treturn nil\n}\n", encoding="utf-8"
    )
    assert index_symbols(tmp_path) == (Symbol("Close", "method", "x.go", 3, "Store"),)


def test_test_mapping_associates_test_files_with_subjects() -> None:
    mappings = map_tests(FIXTURE_REPO)
    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.test_file == "internal/booking/hold_test.go"
    assert mapping.subject_file == "internal/booking/hold.go"
    assert mapping.test_names == ("TestExpiresAt", "TestExpired")


def test_test_mapping_reports_missing_subject_as_none(tmp_path: Path) -> None:
    (tmp_path / "util_test.go").write_text(
        'package x\n\nimport "testing"\n\nfunc TestUtil(t *testing.T) {}\n', encoding="utf-8"
    )
    mappings = map_tests(tmp_path)
    assert len(mappings) == 1
    assert mappings[0].subject_file is None
    assert mappings[0].test_names == ("TestUtil",)


def test_import_graph_reports_internal_edges_both_ways() -> None:
    graph = build_import_graph(FIXTURE_REPO)
    assert graph.imports_of("internal/api") == ("internal/booking",)
    assert graph.imports_of("internal/booking") == ()
    assert graph.dependents_of("internal/booking") == ("internal/api",)
    assert graph.dependents_of("internal/api") == ()


def test_import_graph_without_go_mod_has_no_edges(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "a.go").write_text(
        'package a\n\nimport "example.com/mod/b"\n', encoding="utf-8"
    )
    graph = build_import_graph(tmp_path)
    assert graph.imports_of("a") == ()
