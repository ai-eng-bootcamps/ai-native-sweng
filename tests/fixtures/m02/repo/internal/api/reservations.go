// Package api exposes the bookit HTTP endpoints.
package api

// confirmReservation advances a reservation to confirmed when the transition is allowed.
// It backs POST /reservations/{id}/confirm; the booking package owns the transition rules,
// and the handler only routes the request to them.
func confirmReservation(current, next string) bool {
	return current == "pending" && next == "confirmed"
}
