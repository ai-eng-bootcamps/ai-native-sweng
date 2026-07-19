"""Grader for the m08 fixture task fx-slug-hyphen (course grader exit-code contract).

Run from the working-copy root of the m05 practice fixture with the attempt's patch
applied. Exit 0 = pass, exit 1 = fail, exit 2 = usage/environment error (never a task
judgment). Judgment: the full test suite stays green, and a HIDDEN behavioral test -
the documented multi-word slug form - passes against the changed code. The hidden test
is written, run, and removed by this script; it is never shipped to the attempt.
"""

import pathlib
import shutil
import subprocess
import sys

HIDDEN_TEST = """package directory

import "testing"

func TestSlugHiddenGrader(t *testing.T) {
\tif got := Slug("Main Hall"); got != "main-hall" {
\t\tt.Fatalf("Slug(%q) = %q, want %q", "Main Hall", got, "main-hall")
\t}
}
"""


def go_test(*args: str) -> int:
    """Run go test quietly and report its exit code."""
    return subprocess.run(
        ["go", "test", "-count=1", *args],
        capture_output=True,
        text=True,
    ).returncode


def main() -> int:
    root = pathlib.Path.cwd()
    if not (root / "go.mod").is_file() or not (root / "internal/directory/slug.go").is_file():
        print(
            "usage: run from the working-copy root of the m05 fixture repository", file=sys.stderr
        )
        return 2
    if shutil.which("go") is None:
        print("environment error: the go toolchain is not available", file=sys.stderr)
        return 2
    if go_test("./...") != 0:
        print("fail: the full test suite does not pass", file=sys.stderr)
        return 1
    hidden = root / "internal" / "directory" / "slug_hidden_grader_test.go"
    hidden.write_text(HIDDEN_TEST, encoding="utf-8")
    try:
        hidden_rc = go_test("-run", "HiddenGrader", "./internal/directory/")
    finally:
        hidden.unlink()
    if hidden_rc != 0:
        print("fail: the documented multi-word slug form is not produced", file=sys.stderr)
        return 1
    print("pass: suite green and the hidden behavioral test passes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
