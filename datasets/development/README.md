# Development partition

Supporting material for tasks whose manifests declare `"partition": "development"`
(spec 13.2). Students receive the task description, acceptance criteria, visible tests,
validation commands, and any input fixtures - but never the expected patch.

Current development tasks (manifests live in `datasets/manifests/`):

- `bk-003` - Reject invalid reservation time ranges
- `bk-004` - Diagnose the failing DST availability test
- `bk-005` - Add cancellation-fee tier tests
- `bk-006` - Eliminate the double-booking race
- `bk-008` - Reconcile the cancellation-cutoff docs
- `bk-009` - Review a seeded pagination-fix patch (input fixture in `bk-009/`)
- `bk-010` - Verify the rows-leak review finding

Tasks that need input fixtures get a subdirectory named after their id. Held-out tasks
(`bk-011`, `bk-012`) have no material here; their graders live in the private
course-runner repository.
