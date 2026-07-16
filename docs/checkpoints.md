# Checkpoints and branches

The course provides stable checkpoints so every module and lab has a known-good starting
state, and so target repositories can be reset by revision rather than by manually reversing
changes.

## Naming conventions

Module boundary branches/tags, one pair per module:

```text
course/m00-start
course/m00-complete
course/m01-start
course/m01-complete
...
course/m10-start
course/m10-complete
```

Each lab may additionally provide:

```text
lab/<lab-id>-start        the state a lab begins from
lab/<lab-id>-reference    a reference result for comparison after the lab
```

## Working conventions

- Students normally work on their **own branch**, never directly on checkpoint branches.
- Target repositories are **reset by revision** (via `coursectl reset`) rather than by
  manually reverting changes.
- Module 0 ends at the checkpoint `m00-baseline-complete`: environment configured, target
  tests passing, model configuration valid, and the baseline report recorded. Later modules
  each define their own completion checkpoint (`m01-controlled-development-complete`,
  `m02-readonly-agent-complete`, and so on).
