package booking

import "testing"

// TestCanTransition pins the permitted and rejected reservation status transitions.
func TestCanTransition(t *testing.T) {
	if !CanTransition(StatusPending, StatusConfirmed) {
		t.Fatal("pending -> confirmed must be allowed")
	}
	if !CanTransition(StatusConfirmed, StatusCompleted) {
		t.Fatal("confirmed -> completed must be allowed")
	}
	if CanTransition(StatusCompleted, StatusCancelled) {
		t.Fatal("completed -> cancelled must be rejected")
	}
}
