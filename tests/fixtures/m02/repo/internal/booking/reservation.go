// Package booking models reservations for the bookit platform.
package booking

import "errors"

// Status is the lifecycle state of a reservation.
type Status string

const (
	StatusPending   Status = "pending"
	StatusConfirmed Status = "confirmed"
	StatusCompleted Status = "completed"
	StatusCancelled Status = "cancelled"
)

// errInvalidTransition is returned when a reservation is moved between states
// that the lifecycle does not allow.
var errInvalidTransition = errors.New("booking: invalid reservation state transition")

// Reservation is a single hold placed against a bookable instrument.
type Reservation struct {
	ID     string
	Status Status
}

// Confirm advances a pending reservation to confirmed.
func (r *Reservation) Confirm() error {
	if r.Status != StatusPending {
		return errInvalidTransition
	}
	r.Status = StatusConfirmed
	return nil
}

// Complete advances a confirmed reservation to completed.
func (r *Reservation) Complete() error {
	if r.Status != StatusConfirmed {
		return errInvalidTransition
	}
	r.Status = StatusCompleted
	return nil
}

// Cancel moves a pending or confirmed reservation to cancelled.
func (r *Reservation) Cancel() error {
	if r.Status != StatusPending && r.Status != StatusConfirmed {
		return errInvalidTransition
	}
	r.Status = StatusCancelled
	return nil
}
