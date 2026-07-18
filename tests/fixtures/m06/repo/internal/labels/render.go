package labels

// Render wraps a normalized tag for display.
func Render(label string) string {
	return "[" + label + "]"
}
