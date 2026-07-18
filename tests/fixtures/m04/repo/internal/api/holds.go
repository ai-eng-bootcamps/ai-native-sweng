// Package api exposes the bookit HTTP endpoints.
package api

import (
	"time"

	"github.com/ai-eng-bootcamps/bookit-fixture/internal/booking"
)

// holdActive reports whether a reservation's hold is still active at the given
// instant. The booking package owns the expiry rule; the handler only routes
// the question to it.
func holdActive(h booking.Hold, now time.Time) bool {
	return !h.Expired(now)
}
