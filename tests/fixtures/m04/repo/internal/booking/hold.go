// Package booking models the reservation lifecycle for the bookit platform.
package booking

import "time"

// HoldTTLMinutes pins how long a pending reservation may hold its resource.
const HoldTTLMinutes = 30

// Hold reserves a resource for a pending reservation until it expires.
type Hold struct {
	ReservationID string
	PlacedAt      time.Time
}

// ExpiresAt reports when the hold lapses and the resource is released.
func (h Hold) ExpiresAt() time.Time {
	return h.PlacedAt.Add(HoldTTLMinutes * time.Minute)
}

// Expired reports whether the hold has lapsed at the given instant.
func (h Hold) Expired(now time.Time) bool {
	return !now.Before(h.ExpiresAt())
}
