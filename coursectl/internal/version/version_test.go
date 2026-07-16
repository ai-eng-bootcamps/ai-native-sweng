package version

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestStringDefaults(t *testing.T) {
	assert.Equal(t, "coursectl dev (commit none, built unknown)", String())
}

func TestStringUsesInjectedValues(t *testing.T) {
	// Simulate the ldflags -X injection done by the release workflow.
	origVersion, origCommit, origDate := Version, Commit, Date
	t.Cleanup(func() { Version, Commit, Date = origVersion, origCommit, origDate })

	Version, Commit, Date = "v1.2.3", "abc1234", "2026-07-16T00:00:00Z"
	assert.Equal(t, "coursectl v1.2.3 (commit abc1234, built 2026-07-16T00:00:00Z)", String())
}
