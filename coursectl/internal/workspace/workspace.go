// Package workspace locates the course repository root and manages the
// gitignored workspace/ directory that holds cloned target repositories
// (spec section 10.5).
package workspace

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// DirName is the workspace directory name inside the course repository.
const DirName = "workspace"

// FindRepoRoot walks upward from dir and returns the first directory that
// contains a .git entry.
func FindRepoRoot(dir string) (string, error) {
	abs, err := filepath.Abs(dir)
	if err != nil {
		return "", fmt.Errorf("resolving %s: %w", dir, err)
	}
	for cur := abs; ; {
		if _, err := os.Stat(filepath.Join(cur, ".git")); err == nil {
			return cur, nil
		} else if !errors.Is(err, os.ErrNotExist) {
			return "", fmt.Errorf("checking %s for .git: %w", cur, err)
		}
		parent := filepath.Dir(cur)
		if parent == cur {
			return "", fmt.Errorf("no git repository found in or above %s", abs)
		}
		cur = parent
	}
}

// Ensure creates root/workspace if needed and drops a workspace/.gitignore
// that keeps everything inside it out of version control, so the directory
// stays gitignored regardless of the repository's top-level .gitignore.
// Ensure is idempotent and never overwrites an existing .gitignore.
func Ensure(root string) (string, error) {
	ws := filepath.Join(root, DirName)
	if err := os.MkdirAll(ws, 0o755); err != nil {
		return "", fmt.Errorf("creating %s: %w", ws, err)
	}
	gi := filepath.Join(ws, ".gitignore")
	if _, err := os.Stat(gi); err == nil {
		return ws, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("checking %s: %w", gi, err)
	}
	// "*" ignores everything inside workspace/, including this file.
	if err := os.WriteFile(gi, []byte("*\n"), 0o644); err != nil {
		return "", fmt.Errorf("writing %s: %w", gi, err)
	}
	return ws, nil
}

// Exists reports whether root/workspace exists and is a directory.
func Exists(root string) bool {
	info, err := os.Stat(filepath.Join(root, DirName))
	return err == nil && info.IsDir()
}
