package target

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

const testRev = "0123456789abcdef0123456789abcdef01234567"

// fakeGit records every command and simulates just enough git/go behavior for
// the manager's flows, without shelling out.
type fakeGit struct {
	heads     map[string]string
	calls     [][]string
	worktrees string
	revParse  string
	healthErr error
}

func newFakeGit() *fakeGit { return &fakeGit{heads: map[string]string{}} }

func (f *fakeGit) run(_ context.Context, dir, name string, args ...string) (string, error) {
	f.calls = append(f.calls, append([]string{dir, name}, args...))
	if name == "git" {
		switch args[0] {
		case "clone":
			return "", os.MkdirAll(filepath.Join(args[len(args)-1], ".git"), 0o755)
		case "cat-file":
			return "", nil
		case "checkout", "reset":
			f.heads[dir] = args[len(args)-1]
			return "", nil
		case "rev-parse":
			if f.revParse != "" {
				return f.revParse, nil
			}
			return f.heads[dir] + "\n", nil
		case "worktree":
			if args[1] == "list" {
				return f.worktrees, nil
			}
			return "", nil
		default:
			return "", nil
		}
	}
	if name == "go" {
		return "ok\n", f.healthErr
	}
	return "", nil
}

func (f *fakeGit) ran(want ...string) bool {
	for _, c := range f.calls {
		if len(c) < len(want)+1 {
			continue
		}
		// c[1:] is name+args; match want against name+args prefix.
		ok := true
		for i, w := range want {
			if c[1+i] != w {
				ok = false
				break
			}
		}
		if ok {
			return true
		}
	}
	return false
}

func newManager(t *testing.T, f *fakeGit) *Manager {
	t.Helper()
	m := &Manager{Root: t.TempDir(), Out: &bytes.Buffer{}, Run: f.run}
	// Point the default worktree listing at the clone dir once Root is known.
	if f.worktrees == "" {
		f.worktrees = "worktree " + m.CloneDir(testRepoName) + "\n"
	}
	return m
}

func seedClone(t *testing.T, m *Manager, repoName string) {
	t.Helper()
	assert.NoError(t, os.MkdirAll(filepath.Join(m.CloneDir(repoName), ".git"), 0o755))
}

func TestGuardRejectsUnsafeNames(t *testing.T) {
	m := New(t.TempDir(), &bytes.Buffer{})
	for _, name := range []string{"", ".", "..", "../evil", "a/b", "x..y"} {
		_, err := m.HeadRevision(context.Background(), name)
		assert.Error(t, err, name)
	}
}

func TestCloneIsIdempotent(t *testing.T) {
	f := newFakeGit()
	m := newManager(t, f)
	ctx := context.Background()

	assert.NoError(t, m.Clone(ctx, "test-org/"+testRepoName, testRev))
	assert.True(t, m.Exists(testRepoName))
	nClone := 0
	for _, c := range f.calls {
		if len(c) >= 3 && c[1] == "git" && c[2] == "clone" {
			nClone++
		}
	}
	assert.Equal(t, 1, nClone)

	// Second clone is a no-op: still exactly one git clone recorded.
	assert.NoError(t, m.Clone(ctx, "test-org/"+testRepoName, testRev))
	nClone = 0
	for _, c := range f.calls {
		if len(c) >= 3 && c[1] == "git" && c[2] == "clone" {
			nClone++
		}
	}
	assert.Equal(t, 1, nClone)
}

func TestRestoreMissingCloneFails(t *testing.T) {
	f := newFakeGit()
	m := newManager(t, f)
	err := m.Restore(context.Background(), testRepoName, testRev)
	assert.ErrorContains(t, err, "is missing")
}

func TestResetRunsEightStepsAndArchives(t *testing.T) {
	f := newFakeGit()
	m := newManager(t, f)
	seedClone(t, m, testRepoName)

	// Student report and trace inside the clone must be preserved, not wiped.
	clone := m.CloneDir(testRepoName)
	assert.NoError(t, os.MkdirAll(filepath.Join(clone, "reports"), 0o755))
	assert.NoError(t, os.WriteFile(filepath.Join(clone, "reports", "bk-001.md"), []byte("work"), 0o644))
	assert.NoError(t, os.MkdirAll(filepath.Join(clone, "traces"), 0o755))
	assert.NoError(t, os.WriteFile(filepath.Join(clone, "traces", "run.jsonl"), []byte("{}"), 0o644))

	out := m.Out.(*bytes.Buffer)
	err := m.Reset(context.Background(), testRepoName, testRev)
	assert.NoError(t, err)

	for _, step := range []string{"1/8", "2/8", "3/8", "4/8", "5/8", "6/8", "7/8", "8/8"} {
		assert.Contains(t, out.String(), step)
	}

	// Reports and traces moved out of the clone into the gitignored archive.
	assert.NoDirExists(t, filepath.Join(clone, "reports"))
	assert.NoDirExists(t, filepath.Join(clone, "traces"))
	archive := filepath.Join(m.Root, "workspace", ".archive", testRepoName)
	entries, rerr := os.ReadDir(archive)
	assert.NoError(t, rerr)
	assert.Len(t, entries, 2)

	// The reset actually restored by revision and ran the health check.
	assert.True(t, f.ran("git", "reset", "--hard", testRev))
	assert.True(t, f.ran("git", "clean", "--force", "-d"))
	assert.True(t, f.ran("go", "test", "./..."))
}

func TestResetRemovesLinkedWorktrees(t *testing.T) {
	f := newFakeGit()
	m := newManager(t, f)
	seedClone(t, m, testRepoName)
	extra := filepath.Join(m.Root, "workspace", ".wt", "lab")
	f.worktrees = "worktree " + m.CloneDir(testRepoName) + "\nworktree " + extra + "\n"

	assert.NoError(t, m.Reset(context.Background(), testRepoName, testRev))
	assert.True(t, f.ran("git", "worktree", "remove", "--force", extra))
}

func TestResetFailsOnRevisionMismatch(t *testing.T) {
	f := newFakeGit()
	f.revParse = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"
	m := newManager(t, f)
	seedClone(t, m, testRepoName)

	err := m.Reset(context.Background(), testRepoName, testRev)
	assert.ErrorContains(t, err, "step 7")
	assert.ErrorContains(t, err, "HEAD is")
}

func TestResetFailsOnHealthCheck(t *testing.T) {
	f := newFakeGit()
	f.healthErr = errors.New("test failed")
	m := newManager(t, f)
	seedClone(t, m, testRepoName)

	err := m.Reset(context.Background(), testRepoName, testRev)
	assert.ErrorContains(t, err, "step 8")
}

func TestResetMissingCloneFails(t *testing.T) {
	f := newFakeGit()
	m := newManager(t, f)
	err := m.Reset(context.Background(), testRepoName, testRev)
	assert.ErrorContains(t, err, "is missing")
}

func TestRunValidationUsesShell(t *testing.T) {
	f := newFakeGit()
	m := newManager(t, f)
	seedClone(t, m, testRepoName)

	_, err := m.RunValidation(context.Background(), testRepoName, "git status --porcelain")
	assert.NoError(t, err)
	// The command was handed to a shell as a single string.
	found := false
	for _, c := range f.calls {
		if len(c) >= 4 && (c[1] == "sh" || c[1] == "cmd") && strings.Contains(c[len(c)-1], "git status --porcelain") {
			found = true
		}
	}
	assert.True(t, found)
}

const testRepoName = "target-repo"
