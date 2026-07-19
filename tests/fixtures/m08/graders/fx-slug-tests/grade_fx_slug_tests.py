"""Grader for the m08 fixture task fx-slug-tests (course grader exit-code contract).

Run from the working-copy root of the m05 practice fixture with the attempt's patch
applied. Exit 0 = pass, exit 1 = fail, exit 2 = usage/environment error (never a task
judgment). Judgment, in order:

1. the full test suite passes as submitted;
2. only test files were added or changed (production code untouched);
3. MUTATION check for the tab-padding case: a mutant that stops trimming tabs
   (``strings.TrimSpace`` -> ``strings.Trim(name, " ")``) must be KILLED by the
   suite - the pre-existing tests survive it, so only a new tab-padding test kills it;
4. structural check for the uppercase case: some test in ``internal/directory``
   exercises an all-uppercase quoted input.

The mutant is swapped in and restored by this script; the tree is byte-identical to
the submission afterwards.
"""

import pathlib
import re
import shutil
import subprocess
import sys

ORIGINAL_CALL = "strings.TrimSpace(name)"
MUTANT_CALL = 'strings.Trim(name, " ")'
ALL_CAPS_INPUT = re.compile(r'"[A-Z]{2,}"')


def go_test(*args: str) -> int:
    """Run go test quietly and report its exit code."""
    return subprocess.run(
        ["go", "test", "-count=1", *args],
        capture_output=True,
        text=True,
    ).returncode


def main() -> int:
    root = pathlib.Path.cwd()
    slug = root / "internal" / "directory" / "slug.go"
    if not (root / "go.mod").is_file() or not slug.is_file():
        print(
            "usage: run from the working-copy root of the m05 fixture repository", file=sys.stderr
        )
        return 2
    if shutil.which("go") is None:
        print("environment error: the go toolchain is not available", file=sys.stderr)
        return 2

    if go_test("./...") != 0:
        print("fail: the submitted test suite does not pass", file=sys.stderr)
        return 1

    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if status.returncode != 0:
        print("environment error: git status failed", file=sys.stderr)
        return 2
    for line in status.stdout.splitlines():
        changed = line[3:].strip()
        if not changed.endswith("_test.go"):
            print(f"fail: non-test file changed: {changed}", file=sys.stderr)
            return 1

    original = slug.read_text(encoding="utf-8")
    if ORIGINAL_CALL not in original:
        print("fail: production code changed; the trim call is gone", file=sys.stderr)
        return 1
    slug.write_text(original.replace(ORIGINAL_CALL, MUTANT_CALL), encoding="utf-8")
    try:
        mutant_rc = go_test("./internal/directory/")
    finally:
        slug.write_text(original, encoding="utf-8")
    if mutant_rc == 0:
        print("fail: the tab-padding mutant survives; no test covers tab trimming", file=sys.stderr)
        return 1

    test_files = sorted((root / "internal" / "directory").glob("*_test.go"))
    if not any(ALL_CAPS_INPUT.search(f.read_text(encoding="utf-8")) for f in test_files):
        print("fail: no test exercises an all-uppercase input", file=sys.stderr)
        return 1

    print("pass: suite green, tests-only diff, tab mutant killed, uppercase case covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
