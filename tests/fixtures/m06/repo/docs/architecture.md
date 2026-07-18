# Architecture

Three independent packages compose the tag styling pipeline:

- `internal/tags` normalizes raw tag input.
- `internal/labels` renders a normalized tag as a display label.
- `internal/badges` composes a rendered label into a badge string.

The packages are deliberately decoupled: each can change independently as long
as its documented behavior holds.
