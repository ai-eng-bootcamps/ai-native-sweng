// Package target performs the git operations coursectl runs against target
// repository clones under workspace/. Every operation is confined to
// workspace/<repo>; the package refuses to act on the course (harness)
// repository itself, implementing the spec 12 requirement to "prevent
// accidental modification of the harness repository".
package target

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/workspace"
)

// gitHost is the org URL target repositories are cloned from. They are cloned,
// never forked (spec 10.5).
const gitHost = "https://github.com/"

// Runner runs name+args in dir and returns combined output. It is the single
// external-command seam, injectable so tests do not shell out.
type Runner func(ctx context.Context, dir, name string, args ...string) (string, error)

// Manager operates on target clones under a course repository's workspace/.
type Manager struct {
	// Root is the course repository root; clones live in Root/workspace/.
	Root string
	// Out receives the transparent per-step progress log.
	Out io.Writer
	// Run executes commands; defaults to execRunner.
	Run Runner
}

// New returns a Manager wired to the real command runner.
func New(root string, out io.Writer) *Manager {
	return &Manager{Root: root, Out: out, Run: execRunner}
}

// CloneDir returns the absolute path of a target clone.
func (m *Manager) CloneDir(repoName string) string {
	return filepath.Join(m.Root, workspace.DirName, repoName)
}

// Exists reports whether a target clone is present (has a .git entry).
func (m *Manager) Exists(repoName string) bool {
	if guardRepoName(repoName) != nil {
		return false
	}
	_, err := os.Stat(filepath.Join(m.CloneDir(repoName), ".git"))
	return err == nil
}

// guardRepoName rejects anything that is not a single, safe path element, so a
// clone path can never resolve to the course root or escape workspace/.
func guardRepoName(repoName string) error {
	if repoName == "" || repoName == "." || repoName == ".." ||
		strings.ContainsAny(repoName, `/\`) || strings.Contains(repoName, "..") {
		return fmt.Errorf("unsafe target repository name %q", repoName)
	}
	return nil
}

// guardClone confirms the clone directory sits strictly inside Root/workspace,
// never at the course root. It is called before every destructive operation.
func (m *Manager) guardClone(repoName string) (string, error) {
	if err := guardRepoName(repoName); err != nil {
		return "", err
	}
	ws := filepath.Join(m.Root, workspace.DirName)
	dir := filepath.Join(ws, repoName)
	rel, err := filepath.Rel(ws, dir)
	if err != nil || rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("refusing to operate on %q: outside %s", dir, ws)
	}
	if dir == m.Root {
		return "", errors.New("refusing to operate on the course (harness) repository")
	}
	return dir, nil
}

// Clone clones repoSlug (owner/name) into workspace/<name> and checks out
// revision. It is idempotent: if the clone already exists it is left untouched
// so a re-run never discards student work.
func (m *Manager) Clone(ctx context.Context, repoSlug, revision string) error {
	repoName := filepath.Base(repoSlug)
	dir, err := m.guardClone(repoName)
	if err != nil {
		return err
	}
	if m.Exists(repoName) {
		m.logf("  clone %s: already present at %s, leaving as-is", repoName, dir)
		return nil
	}
	url := gitHost + repoSlug + ".git"
	m.logf("  clone %s from %s", repoName, url)
	if _, err := m.Run(ctx, m.Root, "git", "clone", url, dir); err != nil {
		return fmt.Errorf("cloning %s: %w", repoSlug, err)
	}
	if err := m.checkoutRevision(ctx, dir, revision); err != nil {
		return err
	}
	m.logf("  clone %s: checked out %s", repoName, short(revision))
	return nil
}

// Restore forces a clone's working tree to revision: fetch only if the
// revision is not already local (offline-tolerant), then a hard reset and a
// clean. It underlies both reset step 3 and start-lab.
func (m *Manager) Restore(ctx context.Context, repoName, revision string) error {
	dir, err := m.guardClone(repoName)
	if err != nil {
		return err
	}
	if !m.Exists(repoName) {
		return fmt.Errorf("target clone %s is missing; run 'coursectl setup' first", repoName)
	}
	return m.checkoutRevision(ctx, dir, revision)
}

// checkoutRevision fetches revision if absent, then detaches HEAD at it, hard
// resets, and removes untracked files. Ignored files (build output, *.db) are
// left in place so a health check need not rebuild from scratch.
func (m *Manager) checkoutRevision(ctx context.Context, dir, revision string) error {
	if !m.hasCommit(ctx, dir, revision) {
		m.logf("  fetching %s (revision not present locally)", short(revision))
		if _, err := m.Run(ctx, dir, "git", "fetch", "--quiet", "origin"); err != nil {
			// Offline-tolerant: only fatal if the revision is still missing.
			if !m.hasCommit(ctx, dir, revision) {
				return fmt.Errorf("revision %s not found locally and fetch failed: %w", short(revision), err)
			}
		}
		if !m.hasCommit(ctx, dir, revision) {
			return fmt.Errorf("revision %s not found after fetch", short(revision))
		}
	}
	if _, err := m.Run(ctx, dir, "git", "checkout", "--force", "--detach", revision); err != nil {
		return fmt.Errorf("checking out %s: %w", short(revision), err)
	}
	if _, err := m.Run(ctx, dir, "git", "reset", "--hard", revision); err != nil {
		return fmt.Errorf("hard reset to %s: %w", short(revision), err)
	}
	if _, err := m.Run(ctx, dir, "git", "clean", "--force", "-d"); err != nil {
		return fmt.Errorf("cleaning working tree: %w", err)
	}
	return nil
}

// Reset runs the eight-step lab reset (spec 18) on a target clone.
func (m *Manager) Reset(ctx context.Context, repoName, revision string) error {
	dir, err := m.guardClone(repoName)
	if err != nil {
		return err
	}
	if !m.Exists(repoName) {
		return fmt.Errorf("target clone %s is missing; run 'coursectl setup' first", repoName)
	}

	// Steps 1 and 6 both capture directories that the step-3 clean would
	// otherwise delete, so the capture happens before any destructive git op;
	// each is logged at its own step number below.
	reportsArchive, reportsSaved, err := m.Archive(repoName, "reports")
	if err != nil {
		return fmt.Errorf("step 1 (preserve reports): %w", err)
	}
	tracesArchive, tracesSaved, err := m.Archive(repoName, "traces")
	if err != nil {
		return fmt.Errorf("step 6 (preserve traces): %w", err)
	}

	if reportsSaved {
		m.logf("  1/8 preserved student reports -> %s", reportsArchive)
	} else {
		m.logf("  1/8 no student reports inside the clone to preserve")
	}

	removed, err := m.removeWorktrees(ctx, dir)
	if err != nil {
		return fmt.Errorf("step 2 (remove worktrees): %w", err)
	}
	m.logf("  2/8 removed %d temporary worktree(s)", removed)

	if err := m.checkoutRevision(ctx, dir, revision); err != nil {
		return fmt.Errorf("step 3 (restore revision): %w", err)
	}
	m.logf("  3/8 restored working tree to %s (hard reset + clean)", short(revision))

	// Step 4: Phase-3 target fixtures are tracked files, so the step-3 checkout
	// already restored them; there are no external fixture overlays to apply.
	m.logf("  4/8 fixtures restored via revision checkout (no external overlays)")

	// Step 5: the clone carries no side-channel local state; the hard reset and
	// clean above leave the working tree as the state of record.
	m.logf("  5/8 local state reset (working tree matches the revision)")

	if tracesSaved {
		m.logf("  6/8 preserved traces -> %s (course-level traces/ untouched)", tracesArchive)
	} else {
		m.logf("  6/8 no traces inside the clone; course-level traces/ untouched")
	}

	head, err := m.HeadRevision(ctx, repoName)
	if err != nil {
		return fmt.Errorf("step 7 (verify revision): %w", err)
	}
	if head != revision {
		return fmt.Errorf("step 7 (verify revision): HEAD is %s, expected %s", short(head), short(revision))
	}
	m.logf("  7/8 verified HEAD == %s", short(revision))

	if err := m.HealthCheck(ctx, repoName); err != nil {
		return fmt.Errorf("step 8 (health check): %w", err)
	}
	m.logf("  8/8 health check passed (go test ./...)")
	return nil
}

// HeadRevision returns the clone's current HEAD commit.
func (m *Manager) HeadRevision(ctx context.Context, repoName string) (string, error) {
	dir, err := m.guardClone(repoName)
	if err != nil {
		return "", err
	}
	out, err := m.Run(ctx, dir, "git", "rev-parse", "HEAD")
	if err != nil {
		return "", fmt.Errorf("reading HEAD of %s: %w", repoName, err)
	}
	return strings.TrimSpace(out), nil
}

// HealthCheck runs the target's test suite as the reset health check (spec 18
// step 8).
func (m *Manager) HealthCheck(ctx context.Context, repoName string) error {
	dir, err := m.guardClone(repoName)
	if err != nil {
		return err
	}
	if out, err := m.Run(ctx, dir, "go", "test", "./..."); err != nil {
		return fmt.Errorf("go test ./... failed: %w\n%s", err, out)
	}
	return nil
}

// RunValidation runs one manifest validation command in the clone via the
// platform shell, so command strings behave exactly as a student's shell runs
// them. It returns the combined output and the command's error, if any.
func (m *Manager) RunValidation(ctx context.Context, repoName, command string) (string, error) {
	dir, err := m.guardClone(repoName)
	if err != nil {
		return "", err
	}
	if runtime.GOOS == "windows" {
		return m.Run(ctx, dir, "cmd", "/c", command)
	}
	return m.Run(ctx, dir, "sh", "-c", command)
}

// hasCommit reports whether revision resolves to a commit in the clone.
func (m *Manager) hasCommit(ctx context.Context, dir, revision string) bool {
	_, err := m.Run(ctx, dir, "git", "cat-file", "-e", revision+"^{commit}")
	return err == nil
}

// removeWorktrees removes every linked worktree of the clone (the main
// worktree, which is dir itself, is left in place) and prunes stale entries.
func (m *Manager) removeWorktrees(ctx context.Context, dir string) (int, error) {
	out, err := m.Run(ctx, dir, "git", "worktree", "list", "--porcelain")
	if err != nil {
		return 0, fmt.Errorf("listing worktrees: %w", err)
	}
	removed := 0
	for _, line := range strings.Split(out, "\n") {
		path, ok := strings.CutPrefix(strings.TrimSpace(line), "worktree ")
		if !ok {
			continue
		}
		if filepath.Clean(path) == filepath.Clean(dir) {
			continue // the main worktree
		}
		if _, err := m.Run(ctx, dir, "git", "worktree", "remove", "--force", path); err != nil {
			return removed, fmt.Errorf("removing worktree %s: %w", path, err)
		}
		removed++
	}
	if _, err := m.Run(ctx, dir, "git", "worktree", "prune"); err != nil {
		return removed, fmt.Errorf("pruning worktrees: %w", err)
	}
	return removed, nil
}

// Archive moves a directory out of the clone into a timestamped, gitignored
// archive under workspace/.archive, so student work survives a reset or a lab
// switch. It is a no-op (saved=false) when the directory is absent or empty.
func (m *Manager) Archive(repoName, sub string) (dest string, saved bool, err error) {
	src := filepath.Join(m.CloneDir(repoName), sub)
	entries, err := os.ReadDir(src)
	if err != nil {
		if os.IsNotExist(err) {
			return "", false, nil
		}
		return "", false, fmt.Errorf("reading %s: %w", src, err)
	}
	if len(entries) == 0 {
		return "", false, nil
	}
	stamp := time.Now().UTC().Format("20060102T150405Z")
	dest = filepath.Join(m.Root, workspace.DirName, ".archive", repoName, sub+"-"+stamp)
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return "", false, fmt.Errorf("creating archive dir: %w", err)
	}
	if err := os.Rename(src, dest); err != nil {
		return "", false, fmt.Errorf("archiving %s: %w", src, err)
	}
	return dest, true, nil
}

func (m *Manager) logf(format string, args ...any) {
	if m.Out == nil {
		return
	}
	fmt.Fprintf(m.Out, format+"\n", args...)
}

func short(rev string) string {
	if len(rev) > 12 {
		return rev[:12]
	}
	return rev
}

func execRunner(ctx context.Context, dir, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		return string(out), fmt.Errorf("%s %s: %w", name, strings.Join(args, " "), err)
	}
	return string(out), nil
}
