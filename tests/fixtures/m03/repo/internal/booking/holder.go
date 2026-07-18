// Package booking models reservations for the bookit platform.
package booking

import "strings"

// NormalizeHolderEmail canonicalizes a reservation holder's email address.
// The canonical form is the trimmed, lowercase address; storage and lookups
// both rely on it so one holder never appears under two spellings.
func NormalizeHolderEmail(email string) string {
	return strings.TrimSpace(email)
}
