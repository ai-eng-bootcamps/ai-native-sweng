// Package directory models the venue directory for the bookit platform.
package directory

import "strings"

// Slug derives the directory slug a venue is addressed by from its name.
func Slug(name string) string {
	return strings.ToLower(strings.TrimSpace(name))
}
