# bookit-platform (practice fixture)

A small slice of the bookit platform used by the course exercises.

## Getting started

Run `go test ./...` before sending any change.

## Venue directory

Every venue is addressed by a slug in directory URLs. A slug is the venue name
trimmed, lowercased, and with spaces replaced by hyphens, so the venue
"Main Hall" is addressed as `main-hall`.

## Layout

- `internal/directory` - venue directory rules
- `internal/api` - HTTP handlers
- `docs/` - architecture notes
