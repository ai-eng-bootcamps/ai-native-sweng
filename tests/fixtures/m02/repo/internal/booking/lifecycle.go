// Package booking models the reservation lifecycle for the bookit platform.
package booking

// CanTransition reports whether a reservation may move from one status to another.
// The lifecycle is pending -> confirmed -> completed, with cancelled reachable from
// pending and confirmed. Every other transition is rejected.
func CanTransition(from, to Status) bool {
	switch to {
	case StatusConfirmed:
		return from == StatusPending
	case StatusCompleted:
		return from == StatusConfirmed
	case StatusCancelled:
		return from == StatusPending || from == StatusConfirmed
	default:
		return false
	}
}
