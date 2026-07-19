# Checkpoints and resets

Two different things in this course are loosely called "checkpoints", and they
work differently. This document separates them so you know what to expect.

- **Harness module milestones** (this repository): named states you *reach* by
  finishing a module and verify by running that module's tests. The course does
  not hand you a solution branch or tag.
- **Target-repository checkpoints** (`bookit` and the other targets under
  `workspace/`): real pinned revisions that `coursectl reset --module <n>`
  restores. This is the only "reset to a checkpoint" mechanism, and it applies
  to the targets, never to your harness.

## Harness module milestones (this repository)

Across the course you build the harness in your own copy of this repository
(see `README.md`). Each module ends at a milestone state named
`mNN-<slug>-complete`, for example:

```text
m00-baseline-complete
m01-controlled-development-complete
m02-readonly-agent-complete
m03-safe-writer-complete
m04-context-builder-complete
m05-stateful-workflow-complete
m06-multiworker-complete
m07-reliability-complete
m08-evaluation-complete
```

A milestone is a state you reach, not a branch or tag the course publishes:

- You reach it by completing the module's work in your own copy of the
  repository.
- You verify it yourself by running the tests the module specifies - the
  harness suite with `uv run pytest` (see `README.md`), plus any target checks
  the module calls for. For example, Module 0 is complete when the environment
  is configured, the target tests pass, the model configuration is valid, and
  the baseline report is recorded.
- The course does **not** ship `course/mNN-*` branches, `mNN-*` solution tags,
  or `lab/<lab-id>-reference` states for the harness. Publishing them would
  hand over the reference solution, which the course deliberately withholds; the
  complete reference implementation stays in the private course repository. The
  course is also self-paced, so there is no cohort "after submission" moment at
  which such a branch could be released.
- You may tag your **own** copy if you find it useful
  (`git tag m02-readonly-agent-complete`), and reaching a milestone is a natural
  point to open a pull request within your own repository. That is your own
  bookkeeping, not something the course provides.
- If you get stuck, the path forward is the module's lessons and the supplied
  code, not a handed-over solution. Supplied-code updates arrive at module
  boundaries through the `upstream` remote (see `README.md`); that mechanism is
  separate from any notion of a checkpoint.

## Target-repository checkpoints (`workspace/`)

The course target repositories (`bookit` and the others) are cloned - never
forked - into the gitignored `workspace/` directory (`.gitignore` anchors
`/workspace/`). Each module pins the exact starting revision of its target in
`configs/checkpoints.json`, a map from module number to `{repository,
revision}`. Targets are reset **by revision**, never by tag.

Reset the current module's target to its pinned starting revision with:

```sh
coursectl reset --module <number>      # number is 0-10
```

`reset` resolves the module's checkpoint from `configs/checkpoints.json` and
runs an eight-step reset against that target clone only; it refuses to touch the
harness repository. In order, it:

1. Preserves any student `reports/` inside the clone (moved to a timestamped
   archive under `workspace/.archive/`).
2. Removes temporary worktrees.
3. Restores the working tree to the pinned revision - fetching first only if
   the revision is not already present locally (so it works offline once the
   revision has been fetched), then a hard reset and a clean of untracked
   files.
4. Restores fixtures via that revision checkout (Phase 3 targets carry their
   fixtures as tracked files, so there are no external overlays to apply).
5. Confirms local state matches the revision.
6. Preserves any `traces/` inside the clone (the course-level `traces/` is left
   untouched).
7. Verifies `HEAD` equals the pinned revision.
8. Runs the target's health check (`go test ./...`).

If the target clone is missing, run `coursectl setup` first; setup clones every
target named in the checkpoint map at its pinned revision.

## Related lab commands

Two related commands act on the same target clones and are also implemented
today:

- `coursectl start-lab <lab-id>` prepares a lab's starting state, restoring the
  target to the lab's `starting_revision` (preserving any existing `reports/`
  and `traces/` first).
- `coursectl validate <lab-id>` runs the lab's visible validation commands in
  the clone.

The remaining subcommands (`run-task`, `run-eval`, `replay`, `inspect-trace`,
`cleanup`) validate their arguments today but report which later module brings
their implementation; see `coursectl/README.md`.
