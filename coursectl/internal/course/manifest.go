package course

import (
	"encoding/json"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"regexp"
)

// manifestsDir holds one JSON manifest per task, relative to the course root.
const manifestsDir = "datasets/manifests"

// idPattern is the manifest id format from the dataset schema
// (datasets/manifests/SCHEMA.md). Validating it before building a path also
// keeps a lab id from escaping the manifests directory.
var idPattern = regexp.MustCompile(`^[a-z]+-[0-9]{3}$`)

// Check is one visible validation step a student can run locally
// (datasets/manifests/SCHEMA.md). Command is set only when Kind == "command".
type Check struct {
	Kind        string `json:"kind"`
	Command     string `json:"command"`
	Description string `json:"description"`
}

// Manifest is the subset of a task manifest coursectl needs to prepare and
// validate a lab. The full field list lives in the schema; unlisted fields are
// ignored on load.
type Manifest struct {
	ID               string  `json:"id"`
	Title            string  `json:"title"`
	Repository       string  `json:"repository"`
	StartingRevision string  `json:"starting_revision"`
	VisibleValidation []Check `json:"visible_validation"`
}

// RepoName returns the bare target repository name (the clone directory under
// workspace/).
func (m *Manifest) RepoName() string { return path.Base(m.Repository) }

// LoadManifest reads and validates the manifest for a lab id. The id must
// match the dataset schema, which also prevents path traversal.
func LoadManifest(root, id string) (*Manifest, error) {
	if !idPattern.MatchString(id) {
		return nil, fmt.Errorf("invalid lab id %q: expected the form 'bk-001'", id)
	}
	p := filepath.Join(root, manifestsDir, id+".json")
	data, err := os.ReadFile(p)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("no manifest for lab %q (looked in %s)", id, filepath.Join(manifestsDir, id+".json"))
		}
		return nil, fmt.Errorf("reading manifest %s: %w", p, err)
	}
	var m Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("parsing manifest %s: %w", p, err)
	}
	if m.Repository == "" || m.StartingRevision == "" {
		return nil, fmt.Errorf("manifest %s is missing repository or starting_revision", p)
	}
	return &m, nil
}
