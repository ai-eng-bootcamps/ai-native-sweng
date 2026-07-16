// Package prereq checks that the tools required by the course are
// installed: Git, Go, and Python (spec section 5.4).
package prereq

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
)

// Tool describes one required tool and how to query its version.
type Tool struct {
	// Name is the display name, e.g. "python".
	Name string
	// Candidates are executable names tried in order, e.g. python3 then python.
	Candidates []string
	// VersionArgs are the arguments that print the tool's version.
	VersionArgs []string
}

// DefaultTools returns the local toolchain required by the course.
func DefaultTools() []Tool {
	return []Tool{
		{Name: "git", Candidates: []string{"git"}, VersionArgs: []string{"--version"}},
		{Name: "go", Candidates: []string{"go"}, VersionArgs: []string{"version"}},
		{Name: "python", Candidates: []string{"python3", "python"}, VersionArgs: []string{"--version"}},
	}
}

// Result is the outcome of checking one tool.
type Result struct {
	Name    string
	Path    string
	Version string
	Err     error
}

// OK reports whether the tool was found and its version read.
func (r Result) OK() bool { return r.Err == nil }

// Checker locates tools on PATH and reads their versions. Both function
// fields are injectable so tests do not depend on tools installed on the
// host; nil fields fall back to the real implementations.
type Checker struct {
	// LookPath resolves an executable name to a path. Defaults to exec.LookPath.
	LookPath func(name string) (string, error)
	// RunVersion runs path with args and returns its combined output.
	// Defaults to executing the command.
	RunVersion func(ctx context.Context, path string, args ...string) (string, error)
}

// Check checks every tool and returns one result per tool, in order.
func (c *Checker) Check(ctx context.Context, tools []Tool) []Result {
	results := make([]Result, 0, len(tools))
	for _, t := range tools {
		results = append(results, c.checkOne(ctx, t))
	}
	return results
}

func (c *Checker) checkOne(ctx context.Context, t Tool) Result {
	res := Result{Name: t.Name}
	for _, cand := range t.Candidates {
		path, err := c.lookPath(cand)
		if err != nil {
			continue
		}
		res.Path = path
		out, err := c.runVersion(ctx, path, t.VersionArgs...)
		if err != nil {
			res.Err = fmt.Errorf("reading %s version: %w", t.Name, err)
			return res
		}
		res.Version = firstLine(out)
		return res
	}
	res.Err = fmt.Errorf("%s not found on PATH (tried: %s)", t.Name, strings.Join(t.Candidates, ", "))
	return res
}

func (c *Checker) lookPath(name string) (string, error) {
	if c.LookPath != nil {
		return c.LookPath(name)
	}
	return exec.LookPath(name)
}

func (c *Checker) runVersion(ctx context.Context, path string, args ...string) (string, error) {
	if c.RunVersion != nil {
		return c.RunVersion(ctx, path, args...)
	}
	// CombinedOutput because some tools print their version to stderr.
	out, err := exec.CommandContext(ctx, path, args...).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("running %s %s: %w", path, strings.Join(args, " "), err)
	}
	return string(out), nil
}

func firstLine(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		s = s[:i]
	}
	return strings.TrimSpace(s)
}
