package booking

import "testing"

// TestNormalizeHolderEmail pins the canonical form of holder email addresses.
func TestNormalizeHolderEmail(t *testing.T) {
	if got := NormalizeHolderEmail("  holder@example.com "); got != "holder@example.com" {
		t.Fatalf("normalize should trim surrounding whitespace, got %q", got)
	}
}
