package cli

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/prereq"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/target"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/version"
)

const (
	testRepoSlug = "test-org/target-repo"
	testRepoName = "target-repo"
	testRev      = "0123456789abcdef0123456789abcdef01234567"
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

// fakeGitRunner simulates the git and go commands the target manager runs,
// tracking each clone's HEAD so verification after a reset succeeds. sh/cmd
// validation commands report success. It never shells out.
func fakeGitRunner(heads map[string]string) target.Runner {
	return func(_ context.Context, dir, name string, args ...string) (string, error) {
		if name == "git" {
			switch args[0] {
			case "clone":
				dest := args[len(args)-1]
				if err := os.MkdirAll(filepath.Join(dest, ".git"), 0o755); err != nil {
					return "", err
				}
				return "", nil
			case "cat-file":
				return "", nil // pretend the revision is already local
			case "checkout", "reset":
				heads[dir] = args[len(args)-1]
				return "", nil
			case "rev-parse":
				return heads[dir] + "\n", nil
			case "worktree":
				if args[1] == "list" {
					return "worktree " + dir + "\n", nil
				}
				return "", nil
			default: // fetch, clean, prune, ...
				return "", nil
			}
		}
		if name == "go" {
			return "ok\n", nil // health check passes
		}
		return "", nil // sh -c / cmd /c validation command passes
	}
}

// writeFixture lays down a minimal but complete course repository: a .git
// marker, the checkpoint map, a scripted model config, and one task manifest.
func writeFixture(t *testing.T, root string) {
	t.Helper()
	assert.NoError(t, os.Mkdir(filepath.Join(root, ".git"), 0o755))

	write := func(rel, content string) {
		p := filepath.Join(root, rel)
		assert.NoError(t, os.MkdirAll(filepath.Dir(p), 0o755))
		assert.NoError(t, os.WriteFile(p, []byte(content), 0o644))
	}
	write("configs/checkpoints.json", fmt.Sprintf(
		`{"modules":{"0":{"repository":%q,"revision":%q}}}`, testRepoSlug, testRev))
	write("configs/models/default.toml", "mode = \"scripted\"\n\n[scripted]\nscript = \"scripted-demo.json\"\n")
	write("configs/models/scripted-demo.json", "[]\n")
	write("datasets/manifests/bk-001.json", fmt.Sprintf(`{
      "id":"bk-001","title":"Test lab","repository":%q,"starting_revision":%q,
      "visible_validation":[
        {"kind":"command","command":"git status --porcelain","description":"tree clean"},
        {"kind":"artifact","description":"report exists"}
      ]}`, testRepoSlug, testRev))
}

// seedClone creates a target clone so reset/validate see it as present.
func seedClone(t *testing.T, root string) {
	t.Helper()
	assert.NoError(t, os.MkdirAll(filepath.Join(root, "workspace", testRepoName, ".git"), 0o755))
}

// newTestApp returns an App wired to buffers, a fake toolchain, a fake git
// branch, a fake target manager, and a fully populated course repository as
// the working directory.
func newTestApp(t *testing.T) (*App, *bytes.Buffer, *bytes.Buffer) {
	t.Helper()
	repo := t.TempDir()
	writeFixture(t, repo)
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	heads := map[string]string{}
	app := &App{
		Stdout:  stdout,
		Stderr:  stderr,
		WorkDir: repo,
		Checker: fakeChecker(allTools()),
		GitBranch: func(_ context.Context, _ string) (string, error) {
			return "main", nil
		},
		NewManager: func(root string, out io.Writer) *target.Manager {
			return &target.Manager{Root: root, Out: out, Run: fakeGitRunner(heads)}
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

func TestSingleArgStubsValidateArgs(t *testing.T) {
	cases := []struct {
		cmd    string
		module int
	}{
		{"run-task", 2},
		{"run-eval", 8},
		{"replay", 2},
		{"inspect-trace", 2},
	}
	for _, tc := range cases {
		t.Run(tc.cmd, func(t *testing.T) {
			ctx := context.Background()

			app, _, _ := newTestApp(t)
			err := app.Run(ctx, []string{tc.cmd})
			assert.ErrorContains(t, err, "usage: coursectl "+tc.cmd)

			err = app.Run(ctx, []string{tc.cmd, "id-1", "id-2"})
			assert.ErrorContains(t, err, "usage: coursectl "+tc.cmd)

			err = app.Run(ctx, []string{tc.cmd, "--verbose"})
			assert.ErrorContains(t, err, "usage: coursectl "+tc.cmd)

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

	t.Run("undefined module", func(t *testing.T) {
		app, _, _ := newTestApp(t)
		err := app.Run(ctx, []string{"reset", "--module", "5"})
		assert.ErrorContains(t, err, "not defined")
	})
}

func TestResetRunsEightSteps(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	seedClone(t, app.WorkDir)

	err := app.Run(context.Background(), []string{"reset", "--module", "0"})
	assert.NoError(t, err)
	out := stdout.String()
	for _, step := range []string{"1/8", "2/8", "3/8", "4/8", "5/8", "6/8", "7/8", "8/8"} {
		assert.Contains(t, out, step)
	}
	assert.Contains(t, out, "Module 0 reset complete.")
}

func TestResetMissingCloneFails(t *testing.T) {
	app, _, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"reset", "--module", "0"})
	assert.ErrorContains(t, err, "is missing")
	assert.ErrorContains(t, err, "coursectl setup")
}

func TestSetupClonesTargets(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"setup"})
	assert.NoError(t, err)

	ws := filepath.Join(app.WorkDir, "workspace")
	info, statErr := os.Stat(ws)
	assert.NoError(t, statErr)
	assert.True(t, info.IsDir())
	gi, readErr := os.ReadFile(filepath.Join(ws, ".gitignore"))
	assert.NoError(t, readErr)
	assert.Equal(t, "*\n", string(gi))

	// The target clone was created under workspace/.
	_, cloneErr := os.Stat(filepath.Join(ws, testRepoName, ".git"))
	assert.NoError(t, cloneErr)

	out := stdout.String()
	assert.Contains(t, out, "ok   git")
	assert.Contains(t, out, "ok   go")
	assert.Contains(t, out, "ok   python")
	assert.Contains(t, out, "Course repository root: "+app.WorkDir)
	assert.Contains(t, out, "model config ok: mode=scripted")
	assert.Contains(t, out, "clone "+testRepoName)
	assert.Contains(t, out, "Setup complete.")
}

func TestSetupIsIdempotent(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	ctx := context.Background()
	assert.NoError(t, app.Run(ctx, []string{"setup"}))
	stdout.Reset()
	assert.NoError(t, app.Run(ctx, []string{"setup"}))
	assert.Contains(t, stdout.String(), "already present")
}

func TestSetupFailsOnMissingPrerequisite(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	tools := allTools()
	delete(tools, "python3")
	app.Checker = fakeChecker(tools)

	err := app.Run(context.Background(), []string{"setup"})
	assert.ErrorContains(t, err, "missing prerequisites: python")
	assert.Contains(t, stdout.String(), "FAIL python")

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

func TestSetupFailsOnInvalidModelConfig(t *testing.T) {
	app, _, _ := newTestApp(t)
	assert.NoError(t, os.Remove(filepath.Join(app.WorkDir, "configs/models/default.toml")))

	err := app.Run(context.Background(), []string{"setup"})
	assert.ErrorContains(t, err, "validating model configuration")
}

func TestSetupFailsOutsideRepository(t *testing.T) {
	app, _, _ := newTestApp(t)
	app.WorkDir = t.TempDir() // no .git anywhere under TempDir

	err := app.Run(context.Background(), []string{"setup"})
	assert.ErrorContains(t, err, "locating course repository root")
}

func TestStartLabPreparesTarget(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"start-lab", "bk-001"})
	assert.NoError(t, err)
	out := stdout.String()
	assert.Contains(t, out, "Preparing lab bk-001")
	assert.Contains(t, out, "Lab bk-001 is ready in workspace/"+testRepoName)
	// Clone-on-demand created the target.
	_, statErr := os.Stat(filepath.Join(app.WorkDir, "workspace", testRepoName, ".git"))
	assert.NoError(t, statErr)
}

func TestStartLabPreservesPriorWork(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	seedClone(t, app.WorkDir)
	reports := filepath.Join(app.WorkDir, "workspace", testRepoName, "reports")
	assert.NoError(t, os.MkdirAll(reports, 0o755))
	assert.NoError(t, os.WriteFile(filepath.Join(reports, "prior.md"), []byte("work"), 0o644))

	err := app.Run(context.Background(), []string{"start-lab", "bk-001"})
	assert.NoError(t, err)
	assert.Contains(t, stdout.String(), "preserved existing reports")
	assert.NoDirExists(t, reports)
	assert.FileExists(t, filepath.Join(app.WorkDir, "workspace", ".archive", testRepoName,
		findArchived(t, filepath.Join(app.WorkDir, "workspace", ".archive", testRepoName)), "prior.md"))
}

// findArchived returns the single entry name under dir (the timestamped
// archive folder), failing if there is not exactly one.
func findArchived(t *testing.T, dir string) string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	assert.NoError(t, err)
	assert.Len(t, entries, 1)
	return entries[0].Name()
}

func TestStartLabValidatesArgs(t *testing.T) {
	app, _, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"start-lab"})
	assert.ErrorContains(t, err, "usage: coursectl start-lab")

	err = app.Run(context.Background(), []string{"start-lab", "--flag"})
	assert.ErrorContains(t, err, "usage: coursectl start-lab")
}

func TestStartLabRejectsUnknownLab(t *testing.T) {
	app, _, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"start-lab", "bk-999"})
	assert.ErrorContains(t, err, "no manifest for lab")

	err = app.Run(context.Background(), []string{"start-lab", "not-an-id"})
	assert.ErrorContains(t, err, "invalid lab id")
}

func TestValidatePasses(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	seedClone(t, app.WorkDir)

	err := app.Run(context.Background(), []string{"validate", "bk-001"})
	assert.NoError(t, err)
	out := stdout.String()
	assert.Contains(t, out, "ok   command: git status --porcelain")
	assert.Contains(t, out, "artifact (manual)")
	assert.Contains(t, out, "all visible validation commands passed")
}

func TestValidateReportsFailingCommand(t *testing.T) {
	app, stdout, _ := newTestApp(t)
	seedClone(t, app.WorkDir)
	// A manager whose validation command fails.
	app.NewManager = func(root string, out io.Writer) *target.Manager {
		return &target.Manager{Root: root, Out: out, Run: func(_ context.Context, _, name string, _ ...string) (string, error) {
			if name == "sh" || name == "cmd" {
				return "boom\n", errors.New("exit status 1")
			}
			return "", nil
		}}
	}

	err := app.Run(context.Background(), []string{"validate", "bk-001"})
	assert.ErrorContains(t, err, "1 visible validation command(s) failed")
	assert.Contains(t, stdout.String(), "FAIL command: git status --porcelain")
}

func TestValidateMissingCloneFails(t *testing.T) {
	app, _, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"validate", "bk-001"})
	assert.ErrorContains(t, err, "is missing")
	assert.ErrorContains(t, err, "start-lab bk-001")
}

func TestValidateValidatesArgs(t *testing.T) {
	app, _, _ := newTestApp(t)
	err := app.Run(context.Background(), []string{"validate"})
	assert.ErrorContains(t, err, "usage: coursectl validate")
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
