# bookit (practice fixture)

A small slice of the bookit reservation service used by the course exercises.

## Getting started

Run `go test ./...` before sending any change.

## Reservation holds

A pending reservation places a temporary hold on its resource. Holds expire
automatically after 15 minutes; an expired hold releases the resource for the
next reservation.

## Layout

- `internal/booking` - reservation and hold rules
- `internal/api` - HTTP handlers
- `docs/` - architecture notes
