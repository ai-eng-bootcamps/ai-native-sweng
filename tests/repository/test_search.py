"""Path search, lexical search, and relevance scoring (Module 4, Lesson 4.3).

These fail against the scaffolding stubs and pass once the search tiers are
implemented to the reference behaviour.
"""

from pathlib import Path

import pytest

from anse_harness.repository.search import find_paths, iter_files, lexical_search, score_files

pytestmark = pytest.mark.student_impl

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "m04" / "repo"


def test_iter_files_is_sorted_and_skips_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "c.txt").write_text("c\n", encoding="utf-8")
    assert iter_files(tmp_path) == ("a/c.txt", "b.txt")


def test_find_paths_matches_path_substrings_case_insensitively() -> None:
    assert find_paths(FIXTURE_REPO, "HOLD") == (
        "internal/api/holds.go",
        "internal/booking/hold.go",
        "internal/booking/hold_test.go",
    )


def test_lexical_search_returns_sorted_line_matches() -> None:
    matches = lexical_search(FIXTURE_REPO, "holdttlminutes")
    locations = [(m.path, m.line) for m in matches]
    assert ("internal/booking/hold.go", 7) in locations
    assert locations == sorted(locations)
    assert all("HoldTTLMinutes" in m.text for m in matches)


def test_lexical_search_respects_max_results() -> None:
    assert len(lexical_search(FIXTURE_REPO, "e", max_results=3)) == 3


def test_score_files_ranks_by_weighted_hits_and_breaks_ties_by_path() -> None:
    scores = score_files(FIXTURE_REPO, ["hold", "expire"])
    paths = [fs.path for fs in scores]
    # Every hold-related file scores; files without any term hit are absent.
    assert "internal/booking/hold.go" in paths
    assert "internal/api/holds.go" in paths
    assert "go.mod" not in paths
    assert all(fs.score > 0 for fs in scores)
    ordered = sorted(scores, key=lambda fs: (-fs.score, fs.path))
    assert list(scores) == ordered


def test_score_files_weights_path_hits_above_content_hits(tmp_path: Path) -> None:
    (tmp_path / "hold.go").write_text("package x\n", encoding="utf-8")
    (tmp_path / "other.go").write_text("// mentions hold once\n", encoding="utf-8")
    scores = score_files(tmp_path, ["hold"])
    assert [fs.path for fs in scores] == ["hold.go", "other.go"]
    assert scores[0].score > scores[1].score
