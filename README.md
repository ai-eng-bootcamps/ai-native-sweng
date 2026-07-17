# ai-native-sweng

Student-owned platform repository for the **AI-Native Software Engineering** course.

Across the course you build an **Engineering Harness for Software Development** in this
repository: a controlled platform in which models inspect repositories, use tools, plan and
execute bounded tasks, run validation, and stop at explicit human approval boundaries. The
harness starter, supplied code, helper libraries, and fixtures are published here and evolve
at module boundaries.

## Getting a working copy

You obtain your own copy in one of two ways (full instructions live in Module 0):

- **Fork this repository.** One-click setup and simple upstream syncing. Trade-offs: forks of
  a public repository are public (your coursework is visible), and pull requests from a fork
  default to targeting the course repository, inviting accidental PRs against it.
- **Copy this repository** (GitHub "Use this template", or clone and push to a new
  repository). Your copy can be private, and pull requests stay within your own repository,
  where the course's PR-checkpoint workflow happens. Trade-off: you must add the `upstream`
  remote manually (one documented command) to receive module updates.

Supplied-code updates (new helper files, fixtures) are published to this repository at module
boundaries and pulled from the `upstream` remote. The course target repositories (`bookit`,
`bookit-platform`, `minefield`) are separate repositories that are cloned, never forked;
`coursectl` clones them into the gitignored `workspace/` directory.

## Required toolchain

Install via the official native installers for your operating system:

- **Git**
- **Go** (used by `coursectl` and the course target repositories)
- **Python 3.11+** with [uv](https://docs.astral.sh/uv/) as the package manager

macOS, Linux, and native Windows are all supported. WSL2 and the development container
(`.devcontainer/`) are recommended paths but **never required** by any lab. Docker is
optional: it enables the devcontainer and stronger isolation, but no core lab requires it.

```sh
uv sync          # create the virtual environment and install dev dependencies
uv run pytest    # run the test suite (works offline, no provider SDKs needed)
```

Live model access is optional and off by default; see `docs/model-modes.md`.

## coursectl

Course operations (setup, reset, lab validation) run through the `coursectl` utility, built
separately under `coursectl/` and distributed as prebuilt binaries.

## Repository layout

```text
src/anse_harness/   the harness: models, tools, workers, workflows, tracing, ...
tests/              unit, integration, security, and replay test suites
coursectl/          the Go course control utility (see coursectl/README.md)
configs/            model, policy, workflow, and evaluation configuration
datasets/           practice and development task datasets and manifests
traces/examples/    committed example execution traces (other traces are gitignored)
scripts/            bootstrap wrappers
docs/               checkpoints, trace event format, model modes
workspace/          gitignored; coursectl clones target repositories here
```

Key documentation:

- `docs/checkpoints.md` - harness milestones and target-repository resets
- `docs/trace-events.md` - the trace event standard and JSONL format
- `docs/model-modes.md` - configuring live, scripted, and replay model modes
