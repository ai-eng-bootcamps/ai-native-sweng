package prereq

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestCheckFindsTool(t *testing.T) {
	c := &Checker{
		LookPath: func(name string) (string, error) {
			assert.Equal(t, "git", name)
			return "/usr/bin/git", nil
		},
		RunVersion: func(_ context.Context, path string, args ...string) (string, error) {
			assert.Equal(t, "/usr/bin/git", path)
			assert.Equal(t, []string{"--version"}, args)
			return "git version 2.49.0\n", nil
		},
	}

	tools := []Tool{{Name: "git", Candidates: []string{"git"}, VersionArgs: []string{"--version"}}}
	results := c.Check(context.Background(), tools)

	assert.Len(t, results, 1)
	r := results[0]
	assert.True(t, r.OK())
	assert.Equal(t, "git", r.Name)
	assert.Equal(t, "/usr/bin/git", r.Path)
	assert.Equal(t, "git version 2.49.0", r.Version)
}

func TestCheckUsesFallbackCandidate(t *testing.T) {
	c := &Checker{
		LookPath: func(name string) (string, error) {
			if name == "python" {
				return "/usr/bin/python", nil
			}
			return "", errors.New("not found")
		},
		RunVersion: func(_ context.Context, _ string, _ ...string) (string, error) {
			return "Python 3.12.4", nil
		},
	}

	tools := []Tool{{Name: "python", Candidates: []string{"python3", "python"}, VersionArgs: []string{"--version"}}}
	r := c.Check(context.Background(), tools)[0]

	assert.True(t, r.OK())
	assert.Equal(t, "/usr/bin/python", r.Path)
	assert.Equal(t, "Python 3.12.4", r.Version)
}

func TestCheckReportsMissingTool(t *testing.T) {
	c := &Checker{
		LookPath: func(string) (string, error) {
			return "", errors.New("not found")
		},
		RunVersion: func(_ context.Context, _ string, _ ...string) (string, error) {
			t.Fatal("RunVersion must not be called when the tool is missing")
			return "", nil
		},
	}

	tools := []Tool{{Name: "python", Candidates: []string{"python3", "python"}, VersionArgs: []string{"--version"}}}
	r := c.Check(context.Background(), tools)[0]

	assert.False(t, r.OK())
	assert.ErrorContains(t, r.Err, "python not found on PATH")
	assert.ErrorContains(t, r.Err, "python3, python")
}

func TestCheckReportsVersionFailure(t *testing.T) {
	c := &Checker{
		LookPath: func(string) (string, error) {
			return "/usr/bin/git", nil
		},
		RunVersion: func(_ context.Context, _ string, _ ...string) (string, error) {
			return "", errors.New("exit status 1")
		},
	}

	tools := []Tool{{Name: "git", Candidates: []string{"git"}, VersionArgs: []string{"--version"}}}
	r := c.Check(context.Background(), tools)[0]

	assert.False(t, r.OK())
	assert.ErrorContains(t, r.Err, "reading git version")
	assert.Equal(t, "/usr/bin/git", r.Path)
}

func TestDefaultToolsCoverRequiredToolchain(t *testing.T) {
	names := make([]string, 0, 3)
	for _, tool := range DefaultTools() {
		names = append(names, tool.Name)
	}
	assert.Equal(t, []string{"git", "go", "python"}, names)
}

func TestFirstLine(t *testing.T) {
	assert.Equal(t, "a", firstLine("a\nb\nc"))
	assert.Equal(t, "a", firstLine("  a  \n"))
	assert.Equal(t, "", firstLine(""))
}
