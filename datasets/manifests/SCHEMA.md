# Task manifest format

Every task in the course dataset is described by one machine-readable manifest file in
this directory, named `<id>.json` (for example `bk-002.json`). The format implements the
required and optional field list of the Continuous Project Specification section 13.3,
with vocabularies taken from the Canonical Reference.

## Why JSON

The harness core is stdlib-only Python and `coursectl` is Go; both parse JSON natively
with no third-party dependency. YAML or TOML would add a parser dependency to at least
one of the two consumers, so manifests are plain JSON. A formal JSON Schema lives next
to this document at `task-manifest.schema.json` (draft 2020-12) for editor tooling and
external validators; the offline test `tests/unit/test_task_manifests.py` validates every
manifest with a hand-rolled structural check so the core stays dependency-free.

## File rules

- One task per file; the filename stem must equal the `id` field.
- `id` values are unique across the dataset.
- Manifests are student-visible. Descriptions and acceptance criteria describe observable
  symptoms and desired behavior only - never a planted mechanism, expected patch, or
  internal defect-catalog identifier. Anything that would spoil a task lives in the
  private course-runner repository and is referenced opaquely (see `hidden_validation`).

## Required fields

The first block is the required field list of spec section 13.3.

| Field | Type | Semantics |
|---|---|---|
| `id` | string, `^[a-z]+-[0-9]{3}$` | Stable task identifier (`bk-NNN` for bookit tasks). |
| `title` | string | Short human-readable title. |
| `repository` | string, `owner/name` | Target repository the task runs against. |
| `starting_revision` | string, 40-hex | Commit the task starts from; targets are reset by revision (spec 17). |
| `description` | string | The problem statement, written as symptoms and desired behavior. |
| `acceptance_criteria` | array of string, non-empty | Precise, individually testable statements of done. |
| `constraints` | array of string | Rules the work must obey (conventions, untouchable files, tool limits). |
| `non_goals` | array of string | Explicitly out of scope; doing these counts as unnecessary change. |
| `allowed_capabilities` | array of capability class | Side-effect classes the worker may exercise (vocabulary below). |
| `prohibited_capabilities` | array of capability class | Side-effect classes that must be denied and recorded. |
| `risk_classification` | capability class | The highest side-effect class the task legitimately requires. |
| `visible_validation` | array of check object | Checks the student can run locally (shape below). |
| `hidden_validation` | string, `grader:<id>` | Opaque reference to the hidden grader in the private course-runner repository. Never contains the answer. |
| `baseline_configuration` | string, `A`-`F` | The baseline (spec 15) this task's evaluation compares against. |
| `time_budget` | time class | Coarse wall-clock class (vocabulary below); no fake precision. |
| `cost_budget` | cost class | Coarse model-cost class per spec 21's cost-class language. |
| `expected_artifacts` | array of string, non-empty | What the run must produce (diff, report, tests, trace). |
| `human_review_rubric` | array of rubric item | What a human reviewer scores (shape below). |
| `known_ambiguities` | array of string | Genuinely open decisions the worker must surface or document. |

The second block is required by this dataset in addition to spec 13.3, so that the seed
table of spec section 13.4 (category, partition, module tags) is machine-readable:

| Field | Type | Semantics |
|---|---|---|
| `category` | category enum | Task category from spec 13.1 (vocabulary below). |
| `partition` | `practice` \| `development` \| `held-out` | Dataset partition per spec 13.2. |
| `modules` | array of module tag, non-empty | Where the task is consumed: `M0`-`M10`, `evidence-gates`, `capstone`. |

## Optional fields

Per spec 13.3:

| Field | Type |
|---|---|
| `recommended_context_sources` | array of string (paths or references worth reading first) |
| `expected_failure_modes` | array of string |
| `parallelization_opportunities` | array of string |
| `security_notes` | string |
| `instructor_notes` | string (must remain spoiler-free; real instructor material is private) |

## Object shapes

`visible_validation` items:

```json
{"kind": "command", "command": "go test ./...", "description": "Full test suite passes."}
{"kind": "artifact", "description": "Diff touches only the listing handler and its tests."}
{"kind": "human-review", "description": "Report citations spot-checked against the code."}
```

`kind` is one of `command`, `artifact`, `human-review`; `command` is required when
`kind` is `command`, absent otherwise. Commands run from the root of the target
repository's worktree (`workspace/<repo>` under the course repository); paths into the
course repository are written relative to that, e.g.
`../../datasets/development/bk-009/patch.diff`.

`human_review_rubric` items pair a criterion with its measurement-taxonomy category
(Canonical Reference section 7):

```json
{"criterion": "No unnecessary changes outside the listing path", "metric_category": "outcome"}
```

`metric_category` is one of `outcome`, `process`, `safety`, `economic`, `human-impact`.

## Vocabularies

### Capability classes (Canonical Reference section 6)

Used by `allowed_capabilities`, `prohibited_capabilities`, and `risk_classification`:

| Value | Meaning |
|---|---|
| `class-0-observation` | Observation only: read, list, search, inspect. |
| `class-1-local-reversible` | Local reversible change: edit files in an isolated worktree, apply a patch. |
| `class-2-local-consequential` | Local consequential change: delete files, install dependencies, change build or CI config. |
| `class-3-external-reversible` | External reversible action: draft PRs, draft comments, non-production CI. |
| `class-4-external-consequential` | External consequential action: merge, publish, deploy. |
| `class-5-prohibited` | Prohibited actions: sandbox escape, secret exposure, control bypass. |

Class 5 is always prohibited; it appears only in `prohibited_capabilities`. Task-specific
prohibitions that are finer-grained than a class (for example "do not edit existing
migration files") belong in `constraints`.

### Baseline configurations (spec section 15)

`baseline_configuration` is a single letter: `A` manual/deterministic, `B` existing
coding assistant, `C` single structured model call, `D` single bounded agent,
`E` stateful workflow, `F` multi-worker workflow.

### Time classes

Coarse classes, deliberately imprecise (spec 21):

| Value | Meaning |
|---|---|
| `time-class-short` | Up to roughly 15 minutes of focused work or agent wall-clock. |
| `time-class-medium` | Up to roughly 45 minutes. |
| `time-class-long` | Up to roughly 2 hours. |

### Cost classes

Every task is completable in scripted or replay mode at zero live cost; `cost_budget`
caps the live-mode spend class (spec 21's "approximate cost class"):

| Value | Meaning |
|---|---|
| `cost-class-replay` | No live model calls expected. |
| `cost-class-small` | A few live calls with small context packets. |
| `cost-class-medium` | Tens of calls or repository-scale context. |
| `cost-class-large` | A full bounded agent or workflow run. |

### Categories (spec section 13.1)

`repository-investigation`, `small-feature-implementation`, `targeted-bug-fixing`,
`failing-test-diagnosis`, `test-creation`, `code-review`, `review-finding-verification`,
`targeted-refactoring`, `documentation-correction`, `issue-triage`,
`integration-conflict-resolution`, `release-preparation`.

The seed set (`bk-001` through `bk-012`) covers the first nine; issue triage,
integration conflict resolution, and release preparation are seeded against
`bookit-platform` in a later authoring pass (spec 13.4).

## Partitions and supporting material

- `datasets/practice/` holds solution explanations and expected traces for practice
  tasks (published module by module).
- `datasets/development/` holds task input fixtures for development tasks (for example
  the patch under review in `bk-009`). Expected patches are never published.
- Held-out tasks ship only their manifest; all of their graders stay in the private
  course-runner repository behind the opaque `hidden_validation` reference.
