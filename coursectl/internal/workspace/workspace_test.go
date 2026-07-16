package workspace

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestFindRepoRootFromRoot(t *testing.T) {
	repo := t.TempDir()
	assert.NoError(t, os.Mkdir(filepath.Join(repo, ".git"), 0o755))

	root, err := FindRepoRoot(repo)
	assert.NoError(t, err)
	assert.Equal(t, repo, root)
}

func TestFindRepoRootFromNestedDir(t *testing.T) {
	repo := t.TempDir()
	assert.NoError(t, os.Mkdir(filepath.Join(repo, ".git"), 0o755))
	nested := filepath.Join(repo, "coursectl", "internal", "cli")
	assert.NoError(t, os.MkdirAll(nested, 0o755))

	root, err := FindRepoRoot(nested)
	assert.NoError(t, err)
	assert.Equal(t, repo, root)
}

func TestFindRepoRootNotFound(t *testing.T) {
	dir := t.TempDir()

	_, err := FindRepoRoot(dir)
	assert.ErrorContains(t, err, "no git repository found")
}

func TestEnsureCreatesWorkspaceWithGitignore(t *testing.T) {
	root := t.TempDir()

	ws, err := Ensure(root)
	assert.NoError(t, err)
	assert.Equal(t, filepath.Join(root, DirName), ws)

	info, err := os.Stat(ws)
	assert.NoError(t, err)
	assert.True(t, info.IsDir())

	gi, err := os.ReadFile(filepath.Join(ws, ".gitignore"))
	assert.NoError(t, err)
	assert.Equal(t, "*\n", string(gi))
}

func TestEnsureIsIdempotentAndKeepsExistingGitignore(t *testing.T) {
	root := t.TempDir()

	_, err := Ensure(root)
	assert.NoError(t, err)

	// A student-customized .gitignore must not be overwritten.
	custom := filepath.Join(root, DirName, ".gitignore")
	assert.NoError(t, os.WriteFile(custom, []byte("# customized\n*\n"), 0o644))

	_, err = Ensure(root)
	assert.NoError(t, err)

	gi, err := os.ReadFile(custom)
	assert.NoError(t, err)
	assert.Equal(t, "# customized\n*\n", string(gi))
}

func TestExists(t *testing.T) {
	root := t.TempDir()
	assert.False(t, Exists(root))

	_, err := Ensure(root)
	assert.NoError(t, err)
	assert.True(t, Exists(root))

	// A plain file named "workspace" does not count.
	other := t.TempDir()
	assert.NoError(t, os.WriteFile(filepath.Join(other, DirName), []byte("x"), 0o644))
	assert.False(t, Exists(other))
}
