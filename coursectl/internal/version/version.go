// Package version holds build metadata injected at release time.
//
// The release workflow sets these variables with:
//
//	go build -ldflags "-X <module>/internal/version.Version=... \
//	                   -X <module>/internal/version.Commit=... \
//	                   -X <module>/internal/version.Date=..."
package version

import "fmt"

var (
	// Version is the release version, e.g. "v1.2.3". "dev" for local builds.
	Version = "dev"
	// Commit is the git commit the binary was built from.
	Commit = "none"
	// Date is the UTC build timestamp in RFC 3339 format.
	Date = "unknown"
)

// String returns a single human-readable version line.
func String() string {
	return fmt.Sprintf("coursectl %s (commit %s, built %s)", Version, Commit, Date)
}
