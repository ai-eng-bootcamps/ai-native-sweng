package tags

import "strings"

// Normalize converts a raw tag to its canonical form.
func Normalize(tag string) string {
	return strings.ToLower(tag)
}
