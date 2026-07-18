# Architecture notes

## Venue directory

`internal/directory` owns the slug rules: a venue's slug is derived from its
name in one place, and the API layer never derives slugs itself; it asks the
directory package.

## Packages

`internal/api` depends on `internal/directory`; the directory package has no
dependency on the API layer.
