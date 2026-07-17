"""read_file tool: returns contents and rejects path escapes (spec Module 2: tools validate paths).

These fail against the scaffolding stub and pass once ``ReadFileTool.run`` is
implemented to the reference behaviour in Module 2, Lesson 2.1.
"""

import json
from pathlib import Path

import pytest

from anse_harness.tools.read_file import PathValidationError, ReadFileTool

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m02"
FIXTURE_REPO = FIXTURES / "repo"
TARGET = "internal/booking/reservation.go"


def test_returns_file_contents() -> None:
    # The shipped schema fixture must match the tool's supplied contract, so a
    # student build produces the same request the recorded trace expects.
    assert ReadFileTool.input_schema == json.loads(
        (FIXTURES / "read_file.schema.json").read_text(encoding="utf-8")
    )

    result = ReadFileTool(FIXTURE_REPO).run({"path": TARGET})
    assert result.ok
    assert result.output == (FIXTURE_REPO / TARGET).read_text(encoding="utf-8")
    assert "StatusConfirmed" in result.output


@pytest.mark.parametrize(
    "bad_path",
    [
        "../../../../etc/passwd",  # traversal above the repo root
        "/etc/passwd",  # absolute path outside the repo
        "internal/../../secrets.txt",  # traversal that escapes after a valid prefix
    ],
)
def test_rejects_paths_outside_repo(bad_path: str) -> None:
    with pytest.raises(PathValidationError):
        ReadFileTool(FIXTURE_REPO).run({"path": bad_path})


def test_missing_file_reports_not_ok() -> None:
    result = ReadFileTool(FIXTURE_REPO).run({"path": "internal/booking/missing.go"})
    assert not result.ok
    assert result.error is not None
