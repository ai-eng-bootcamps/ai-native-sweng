// Package course reads the versioned course metadata that coursectl acts on:
// the module->checkpoint map (configs/checkpoints.json), task manifests
// (datasets/manifests/<id>.json), and the model configuration
// (configs/models/default.toml). It only reads and validates data; the git
// operations that act on target clones live in the target package.
package course

import (
	"encoding/json"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"strconv"
)

// checkpointsPath is the module->checkpoint map, relative to the course root.
const checkpointsPath = "configs/checkpoints.json"

// Checkpoint is the target a module resets to: a repository (owner/name) and
// the exact revision. Targets are reset by revision, never by tag (spec 17).
type Checkpoint struct {
	Repository string `json:"repository"`
	Revision   string `json:"revision"`
}

// RepoName returns the bare repository name (the clone directory under
// workspace/), e.g. "ai-native-sweng-bookit" for
// "ai-eng-bootcamps/ai-native-sweng-bookit".
func (c Checkpoint) RepoName() string { return path.Base(c.Repository) }

// checkpointsFile is the on-disk shape of configs/checkpoints.json.
type checkpointsFile struct {
	Modules map[string]Checkpoint `json:"modules"`
}

// LoadCheckpoints reads and validates the module->checkpoint map. The map is
// the single source of truth for module resets (spec 17-18); it is keyed by
// module number as a string.
func LoadCheckpoints(root string) (map[string]Checkpoint, error) {
	p := filepath.Join(root, checkpointsPath)
	data, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("reading checkpoint map %s: %w", p, err)
	}
	var file checkpointsFile
	if err := json.Unmarshal(data, &file); err != nil {
		return nil, fmt.Errorf("parsing checkpoint map %s: %w", p, err)
	}
	if len(file.Modules) == 0 {
		return nil, fmt.Errorf("checkpoint map %s has no modules", p)
	}
	for key, cp := range file.Modules {
		if cp.Repository == "" || cp.Revision == "" {
			return nil, fmt.Errorf("checkpoint map %s: module %q is missing repository or revision", p, key)
		}
	}
	return file.Modules, nil
}

// ModuleCheckpoint returns the checkpoint a module resets to.
func ModuleCheckpoint(root string, module int) (Checkpoint, error) {
	modules, err := LoadCheckpoints(root)
	if err != nil {
		return Checkpoint{}, err
	}
	cp, ok := modules[strconv.Itoa(module)]
	if !ok {
		return Checkpoint{}, fmt.Errorf("module %d is not defined in %s", module, checkpointsPath)
	}
	return cp, nil
}

// TargetRepos returns the distinct target repositories referenced by the
// checkpoint map, each paired with the revision of the lowest-numbered module
// that references it. setup clones these into workspace/. Ordering is by
// repository name so setup output is stable.
func TargetRepos(root string) ([]Checkpoint, error) {
	modules, err := LoadCheckpoints(root)
	if err != nil {
		return nil, err
	}
	// Pick, per repository, the checkpoint of the lowest module number.
	lowest := map[string]int{}
	chosen := map[string]Checkpoint{}
	for key, cp := range modules {
		n, err := strconv.Atoi(key)
		if err != nil {
			return nil, fmt.Errorf("checkpoint map: module key %q is not a number: %w", key, err)
		}
		if cur, ok := lowest[cp.Repository]; !ok || n < cur {
			lowest[cp.Repository] = n
			chosen[cp.Repository] = cp
		}
	}
	repos := make([]Checkpoint, 0, len(chosen))
	for _, cp := range chosen {
		repos = append(repos, cp)
	}
	sortCheckpoints(repos)
	return repos, nil
}

func sortCheckpoints(cs []Checkpoint) {
	// Simple insertion sort by repository; the slice is tiny (one per repo).
	for i := 1; i < len(cs); i++ {
		for j := i; j > 0 && cs[j].Repository < cs[j-1].Repository; j-- {
			cs[j], cs[j-1] = cs[j-1], cs[j]
		}
	}
}
