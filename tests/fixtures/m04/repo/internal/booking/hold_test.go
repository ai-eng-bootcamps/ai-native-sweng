package booking

import (
	"testing"
	"time"
)

func TestExpiresAt(t *testing.T) {
	placed := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	h := Hold{ReservationID: "r-1", PlacedAt: placed}
	want := placed.Add(30 * time.Minute)
	if !h.ExpiresAt().Equal(want) {
		t.Fatalf("ExpiresAt() = %v, want %v", h.ExpiresAt(), want)
	}
}

func TestExpired(t *testing.T) {
	placed := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	h := Hold{ReservationID: "r-1", PlacedAt: placed}
	if h.Expired(placed.Add(29 * time.Minute)) {
		t.Fatal("hold reported expired before its lifetime elapsed")
	}
	if !h.Expired(placed.Add(30 * time.Minute)) {
		t.Fatal("hold reported active after its lifetime elapsed")
	}
}
