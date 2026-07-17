package course

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
)

func write(t *testing.T, root, rel, content string) {
	t.Helper()
	p := filepath.Join(root, rel)
	assert.NoError(t, os.MkdirAll(filepath.Dir(p), 0o755))
	assert.NoError(t, os.WriteFile(p, []byte(content), 0o644))
}

func TestLoadCheckpoints(t *testing.T) {
	root := t.TempDir()
	write(t, root, checkpointsPath, `{"modules":{
		"0":{"repository":"org/repo-a","revision":"aaa"},
		"1":{"repository":"org/repo-a","revision":"bbb"}}}`)

	modules, err := LoadCheckpoints(root)
	assert.NoError(t, err)
	assert.Len(t, modules, 2)
	assert.Equal(t, "org/repo-a", modules["0"].Repository)
	assert.Equal(t, "repo-a", modules["0"].RepoName())
}

func TestLoadCheckpointsRejectsEmptyAndIncomplete(t *testing.T) {
	root := t.TempDir()
	write(t, root, checkpointsPath, `{"modules":{}}`)
	_, err := LoadCheckpoints(root)
	assert.ErrorContains(t, err, "no modules")

	write(t, root, checkpointsPath, `{"modules":{"0":{"repository":"org/r"}}}`)
	_, err = LoadCheckpoints(root)
	assert.ErrorContains(t, err, "missing repository or revision")
}

func TestModuleCheckpoint(t *testing.T) {
	root := t.TempDir()
	write(t, root, checkpointsPath, `{"modules":{"0":{"repository":"org/repo","revision":"deadbeef"}}}`)

	cp, err := ModuleCheckpoint(root, 0)
	assert.NoError(t, err)
	assert.Equal(t, "deadbeef", cp.Revision)

	_, err = ModuleCheckpoint(root, 7)
	assert.ErrorContains(t, err, "not defined")
}

func TestTargetReposPicksLowestModulePerRepo(t *testing.T) {
	root := t.TempDir()
	write(t, root, checkpointsPath, `{"modules":{
		"0":{"repository":"org/repo-a","revision":"a0"},
		"1":{"repository":"org/repo-a","revision":"a1"},
		"2":{"repository":"org/repo-b","revision":"b2"}}}`)

	repos, err := TargetRepos(root)
	assert.NoError(t, err)
	assert.Len(t, repos, 2)
	// Sorted by repository; repo-a takes module 0's revision.
	assert.Equal(t, "org/repo-a", repos[0].Repository)
	assert.Equal(t, "a0", repos[0].Revision)
	assert.Equal(t, "org/repo-b", repos[1].Repository)
}

func TestLoadManifest(t *testing.T) {
	root := t.TempDir()
	write(t, root, filepath.Join(manifestsDir, "bk-001.json"), `{
		"id":"bk-001","title":"T","repository":"org/repo","starting_revision":"abc",
		"visible_validation":[{"kind":"command","command":"go test ./...","description":"d"}]}`)

	m, err := LoadManifest(root, "bk-001")
	assert.NoError(t, err)
	assert.Equal(t, "repo", m.RepoName())
	assert.Equal(t, "abc", m.StartingRevision)
	assert.Len(t, m.VisibleValidation, 1)
	assert.Equal(t, "go test ./...", m.VisibleValidation[0].Command)
}

func TestLoadManifestRejectsBadIDAndMissing(t *testing.T) {
	root := t.TempDir()
	_, err := LoadManifest(root, "../etc/passwd")
	assert.ErrorContains(t, err, "invalid lab id")

	_, err = LoadManifest(root, "bk-999")
	assert.ErrorContains(t, err, "no manifest for lab")
}

func TestValidateModelConfig(t *testing.T) {
	root := t.TempDir()
	base := "configs/models"

	// scripted: referenced script must exist.
	write(t, root, filepath.Join(base, "default.toml"), "mode = \"scripted\"\n[scripted]\nscript = \"s.json\"\n")
	_, err := ValidateModelConfig(root)
	assert.ErrorContains(t, err, "not found")
	write(t, root, filepath.Join(base, "s.json"), "[]")
	summary, err := ValidateModelConfig(root)
	assert.NoError(t, err)
	assert.Contains(t, summary, "mode=scripted")

	// replay: referenced trace must exist.
	write(t, root, filepath.Join(base, "default.toml"), "mode = \"replay\"\n[replay]\ntrace = \"t.jsonl\"\n")
	write(t, root, filepath.Join(base, "t.jsonl"), "{}")
	summary, err = ValidateModelConfig(root)
	assert.NoError(t, err)
	assert.Contains(t, summary, "mode=replay")

	// live: model id required.
	write(t, root, filepath.Join(base, "default.toml"), "mode = \"live\"\n[live]\nprovider = \"anthropic\"\nmodel = \"claude-x\"\n")
	summary, err = ValidateModelConfig(root)
	assert.NoError(t, err)
	assert.Contains(t, summary, "model=claude-x")

	// invalid mode.
	write(t, root, filepath.Join(base, "default.toml"), "mode = \"nope\"\n")
	_, err = ValidateModelConfig(root)
	assert.ErrorContains(t, err, "mode must be")
}
