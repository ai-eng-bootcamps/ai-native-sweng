package directory

import "testing"

func TestSlugLowercases(t *testing.T) {
	if got := Slug("Atrium"); got != "atrium" {
		t.Fatalf("Slug(%q) = %q, want %q", "Atrium", got, "atrium")
	}
}

func TestSlugTrims(t *testing.T) {
	if got := Slug("  Atrium "); got != "atrium" {
		t.Fatalf("Slug(%q) = %q, want %q", "  Atrium ", got, "atrium")
	}
}
