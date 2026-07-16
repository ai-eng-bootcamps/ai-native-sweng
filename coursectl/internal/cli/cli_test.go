package cli

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/prereq"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/version"
)

// fakeChecker resolves only the executables listed in found and reports a
// fixed version string, so tests never depend on host tools.
func fakeChecker(found map[string]string) *prereq.Checker {
	return &prereq.Checker{
		LookPath: func(name string) (string, error) {
			if p, ok := found[name]; ok {
				return p, nil
			}
			return "", errors.New("executable file not found in $PATH")
		},
		RunVersion: func(_ context.Context, path string, _ ...string) (string, error) {
			return "fake version 1.0 via " + path, nil
		},
	}
}

func allTools() map[string]string {
	return map[string]string{
		"git":     "/usr/bin/git",
		"go":      "/usr/local/go/bin/go",
		"python3": "/usr/bin/python3",
	}
}

// newTestApp returns an App wired to buffers, a fake toolchain, a fake git
// branch, and a temporary git repository as the working directory.
func newTestApp(t *testing.T) (*App, *bytes.Buffer, *bytes.Buffer) {
	t.Helper()
	repo := t.TempDir()
	assert.NoError(t, os.Mkdir(filepath.Join(repo, ".git"), 0o755))
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	app := &App{
		Stdout:  stdout,
		Stderr:  stderr,
		WorkDir: repo,
		Checker: fakeChecker(allTools()),
		GitBranch: func(_ context.Context, _ string) (string, error) {
			return "main", nil
		},
	}
	return app, stdout, stderr
}

func TestRunNoCommand(t *testing.T) {
	app, _, stderr := newTestApp(t)
	err := app.Run(context.Background(), nil)
	assert.EqualError(t, err, "no command given")
	assert.Contains(t, stderr.String(), "Usage: coursectl")
}

func TestRunUnknownCommand(t *testing.T) {
	app, _, stderr := newTestApp(t)
	err := app.Run(context.Background(), []string{"frobnicate"})
	assert.EqualError(t, err, `unknown command "frobnicate"`)
	assert.Contains(t, stderr.String(), "Usage: coursectl")
}

func TestHelpListsEveryCommand(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"help"})
	assert.NoError(t, err)
	for _, name := range []string{
		"setup", "status", "reset", "start-lab", "validate", "run-task",
		"run-eval", "replay", "inspect-trace", "cleanup", "version",
	} {
		assert.Contains(t, stdout.String(), name)
	}
}

func TestVersionOutput(t *testing.T) {
	for _, args := range [][]string{{"version"}, {"--version"}} {
		app, stdout, _ := newTestApp(t)
		err := app.Run(context.Background(), args)
		assert.NoError(t, err)
		out := stdout.String()
		assert.Contains(t, out, "coursectl "+version.Version)
		assert.Contains(t, out, version.Commit)
		assert.Contains(t, out, version.Date)
	}
}

func TestVersionRejectsArgs(t *testing.T) {
	app, _, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"version", "extra"})
	assert.EqualError(t, err, "usage: coursectl version")
}

func TestSingleArgCommandsValidateArgs(t *testing.T) {
	cases := []struct {
		cmd    string
		module int
	}{
		{"start-lab", 0},
		{"validate", 0},
		{"run-task", 2},
		{"run-eval", 8},
		{"replay", 2},
		{"inspect-trace", 2},
	}
	for _, tc := range cases {
		t.Run(tc.cmd, func(t *testing.T) {
			ctx := context.Background()

			// Missing argument fails with usage.
			app, _, _ := newTestApp(t)
			err := app.Run(ctx, []string{tc.cmd})
			assert.ErrorContains(t, err, "usage: coursectl "+tc.cmd)

			// Too many arguments fails with usage.
			err = app.Run(ctx, []string{tc.cmd, "id-1", "id-2"})
			assert.ErrorContains(t, err, "usage: coursectl "+tc.cmd)

			// A flag is not an id.
			err = app.Run(ctx, []string{tc.cmd, "--verbose"})
			assert.ErrorContains(t, err, "usage: coursectl "+tc.cmd)

			// A valid id reaches the explicit not-implemented error.
			err = app.Run(ctx, []string{tc.cmd, "some-id"})
			assert.ErrorContains(t, err, "not implemented in this skeleton")
			assert.ErrorContains(t, err, fmt.Sprintf("module %d", tc.module))
		})
	}
}

func TestCleanupValidatesArgs(t *testing.T) {
	app, _, _ := newTestApp(t)
	ctx := context.Background()

	err := app.Run(ctx, []string{"cleanup", "extra"})
	assert.EqualError(t, err, "usage: coursectl cleanup")

	err = app.Run(ctx, []string{"cleanup"})
	assert.ErrorContains(t, err, "not implemented in this skeleton")
}

func TestResetValidatesModuleFlag(t *testing.T) {
	ctx := context.Background()

	t.Run("missing flag", func(t *testing.T) {
		app, _, _ := newTestApp(t)
		err := app.Run(ctx, []string{"reset"})
		assert.ErrorContains(t, err, "module must be 0-10")
	})

	t.Run("out of range", func(t *testing.T) {
		app, _, _ := newTestApp(t)
		err := app.Run(ctx, []string{"reset", "--module", "11"})
		assert.ErrorContains(t, err, "module must be 0-10")
	})

	t.Run("non-numeric", func(t *testing.T) {
		app, _, _ := newTestApp(t)
		err := app.Run(ctx, []string{"reset", "--module", "abc"})
		assert.ErrorContains(t, err, "parsing reset flags")
	})

	t.Run("unexpected positional", func(t *testing.T) {
		app, _, _ := newTestApp(t)
		err := app.Run(ctx, []string{"reset", "--module", "3", "extra"})
		assert.ErrorContains(t, err, "unexpected argument")
	})

	t.Run("valid module reaches not-implemented", func(t *testing.T) {
		app, _, _ := newTestApp(t)
		err := app.Run(ctx, []string{"reset", "--module", "3"})
		assert.ErrorContains(t, err, "reset --module 3")
		assert.ErrorContains(t, err, "not implemented in this skeleton")
	})
}

func TestSetupCreatesWorkspace(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"setup"})
	assert.NoError(t, err)

	// Workspace directory and its self-gitignore exist.
	ws := filepath.Join(app.WorkDir, "workspace")
	info, statErr := os.Stat(ws)
	assert.NoError(t, statErr)
	assert.True(t, info.IsDir())
	gi, readErr := os.ReadFile(filepath.Join(ws, ".gitignore"))
	assert.NoError(t, readErr)
	assert.Equal(t, "*\n", string(gi))

	out := stdout.String()
	assert.Contains(t, out, "ok   git")
	assert.Contains(t, out, "ok   go")
	assert.Contains(t, out, "ok   python")
	assert.Contains(t, out, "Course repository root: "+app.WorkDir)
	assert.Contains(t, out, "not yet published")
	for _, repo := range targetRepos {
		assert.Contains(t, out, repo)
	}
}

func TestSetupIsIdempotent(t *testing.T) {
	app, _, _ := newTestApp(t)
	ctx := context.Background()
	assert.NoError(t, app.Run(ctx, []string{"setup"}))
	assert.NoError(t, app.Run(ctx, []string{"setup"}))
}

func TestSetupFailsOnMissingPrerequisite(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	tools := allTools()
	delete(tools, "python3")
	app.Checker = fakeChecker(tools)

	err := app.Run(context.Background(), []string{"setup"})
	assert.ErrorContains(t, err, "missing prerequisites: python")
	assert.Contains(t, stdout.String(), "FAIL python")

	// No workspace is created when prerequisites are missing.
	_, statErr := os.Stat(filepath.Join(app.WorkDir, "workspace"))
	assert.True(t, os.IsNotExist(statErr))
}

func TestSetupUsesPythonFallback(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	tools := allTools()
	delete(tools, "python3")
	tools["python"] = "/usr/bin/python"
	app.Checker = fakeChecker(tools)

	err := app.Run(context.Background(), []string{"setup"})
	assert.NoError(t, err)
	assert.Contains(t, stdout.String(), "/usr/bin/python")
}

func TestSetupFailsOutsideRepository(t *testing.T) {
	app, _, _ := newTestApp(t)
	app.WorkDir = t.TempDir() // no .git anywhere under TempDir

	err := app.Run(context.Background(), []string{"setup"})
	assert.ErrorContains(t, err, "locating course repository root")
}

func TestStatusReportsEnvironment(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	ctx := context.Background()
	assert.NoError(t, app.Run(ctx, []string{"setup"}))
	stdout.Reset()

	err := app.Run(ctx, []string{"status"})
	assert.NoError(t, err)
	out := stdout.String()
	assert.Contains(t, out, "Repository root: "+app.WorkDir)
	assert.Contains(t, out, "(present)")
	assert.Contains(t, out, "Git branch:      main")
	assert.Contains(t, out, "ok   git")
}

func TestStatusReportsMissingWorkspace(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"status"})
	assert.NoError(t, err)
	assert.Contains(t, stdout.String(), "Workspace:       missing")
}

func TestStatusOutsideRepositoryStillSucceeds(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	app.WorkDir = t.TempDir()

	err := app.Run(context.Background(), []string{"status"})
	assert.NoError(t, err)
	assert.Contains(t, stdout.String(), "Repository root: not found")
}
