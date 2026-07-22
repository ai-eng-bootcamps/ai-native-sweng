# coursectl

`coursectl` is the course control utility for the AI-Native Software
Engineering course. It is the primary operational interface for students on
macOS, Linux, and native Windows: environment setup, status checks, lab
resets, task execution, evaluations, and trace inspection all go through it
(course spec, section 12).

The tool stays transparent by design: it prints every action it takes or
plans to take in plain text, and it never hides the architectural concepts
students learn in the course.

## Students never compile this tool

`coursectl` is distributed as prebuilt static binaries for macOS, Linux, and
Windows, built by CI and attached to GitHub Releases. Students install it
with a thin bootstrap wrapper from the repository root:

```
./scripts/bootstrap.sh    # macOS / Linux
./scripts/bootstrap.ps1   # Windows (PowerShell)
```

Both wrappers behave identically: they detect your OS and architecture,
download the matching archive from the latest release, verify its SHA256
checksum, and extract the binary into `./bin/`.

## Commands

| Command | Description |
| --- | --- |
| `coursectl setup` | Verify prerequisites (git, go, python) and prepare the gitignored `workspace/` directory for target-repository clones. |
| `coursectl status` | Report repository root, workspace presence, prerequisite versions, and the current git branch. |
| `coursectl reset --module <number>` | Reset target repositories to a module starting checkpoint (by revision, never by reversing changes). |
| `coursectl start-lab <lab-id>` | Prepare the starting state for a lab. |
| `coursectl validate <lab-id>` | Run the validation checks for a lab. |
| `coursectl run-task <task-id>` | Execute a task from the task dataset. |
| `coursectl run-eval <evaluation-id>` | Run an evaluation and collect its metrics. |
| `coursectl replay <run-id>` | Replay a captured run from its stored trace. |
| `coursectl inspect-trace <run-id>` | Print the structured trace of a run. |
| `coursectl cleanup` | Remove temporary worktrees and stale lab state. |
| `coursectl version` | Print version, commit, and build date. |

Phase 3 release: `setup`, `status`, `version`, `reset`, `start-lab`, and
`validate` are fully functional. `setup` clones the target repositories named
in the checkpoint map (`configs/checkpoints.json`) into `workspace/` at their
pinned revision; `reset --module <n>` runs the eight-step reset (spec 18)
against the target clone, never the harness repository; `start-lab` and
`validate` resolve a lab id against the task dataset. The remaining commands
(`run-task`, `run-eval`, `replay`, `inspect-trace`, `cleanup`) validate their
arguments and then report that they are not implemented in this skeleton and
that the course runs these workflows through the Python harness (`uv run`);
they never fake behavior.

## Building and testing locally (maintainers)

Requires the Go toolchain version pinned in `go.mod`.

```
cd coursectl
go build ./...
go vet ./...
go test -race ./...
```

A local build reports its version as `dev`. Release version metadata is
injected by the release workflow through `-ldflags -X` into
`internal/version`.

## Cutting a release (maintainers)

Tag the commit to release with `coursectl/vX.Y.Z` and push the tag:

```
git tag coursectl/v0.1.0
git push origin coursectl/v0.1.0
```

The `coursectl-release` GitHub Actions workflow then runs the tests, builds
CGO-free static binaries for darwin/amd64, darwin/arm64, linux/amd64,
linux/arm64, and windows/amd64, packages them as `.tar.gz` (unix) and `.zip`
(Windows) archives with a `SHA256SUMS` file, and publishes everything as a
GitHub Release. The bootstrap wrappers always fetch the latest release.
