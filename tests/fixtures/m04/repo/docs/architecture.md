# Architecture notes

## Holds

`internal/booking` owns the hold rules. `HoldTTLMinutes` pins the hold
lifetime: a hold placed at time T expires at T plus 30 minutes, and the API
layer never computes expiry itself; it asks the booking package.

## Packages

`internal/api` depends on `internal/booking`; the booking package has no
dependency on the API layer.
