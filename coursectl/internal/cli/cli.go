// Package cli implements the coursectl command-line interface.
//
// Design note (spec section 12): coursectl must stay transparent and must
// not hide the architectural concepts students learn. Output is plain text
// that names every action the tool takes or plans to take; commands that
// are not implemented yet say so explicitly instead of faking behavior.
package cli

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/course"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/prereq"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/target"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/version"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/workspace"
)

// App carries the dependencies commands need. Fields are injectable so
// tests do not depend on host tools or the real repository.
type App struct {
	Stdout io.Writer
	Stderr io.Writer
	// WorkDir is the directory repo-root discovery starts from.
	WorkDir string
	// Checker verifies the required local toolchain.
	Checker *prereq.Checker
	// GitBranch returns the current branch of the repository at root.
	// Defaults to running git.
	GitBranch func(ctx context.Context, root string) (string, error)
	// NewManager builds the target-clone manager for a course root.
	// Defaults to target.New; injectable so tests do not run git.
	NewManager func(root string, out io.Writer) *target.Manager
}

// manager returns the target-clone manager for root, using the injected
// factory when present.
func (a *App) manager(root string) *target.Manager {
	if a.NewManager != nil {
		return a.NewManager(root, a.Stdout)
	}
	return target.New(root, a.Stdout)
}

// Run parses args and executes the selected command. A non-nil error means
// the invocation failed; the caller maps it to a nonzero exit code.
func Run(ctx context.Context, args []string, stdout, stderr io.Writer) error {
	wd, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("determining working directory: %w", err)
	}
	app := &App{Stdout: stdout, Stderr: stderr, WorkDir: wd, Checker: &prereq.Checker{}}
	return app.Run(ctx, args)
}

// Run dispatches to the command named by args[0].
func (a *App) Run(ctx context.Context, args []string) error {
	if len(args) == 0 {
		a.printUsage(a.Stderr)
		return fmt.Errorf("no command given")
	}
	name := args[0]
	switch name {
	case "help", "-h", "-help", "--help":
		a.printUsage(a.Stdout)
		return nil
	case "-version", "--version":
		name = "version"
		args = args[:1]
	}
	for _, c := range commands() {
		if c.name == name {
			return c.run(ctx, a, args[1:])
		}
	}
	a.printUsage(a.Stderr)
	return fmt.Errorf("unknown command %q", name)
}

// command is one coursectl subcommand.
type command struct {
	name    string
	argHint string
	summary string
	run     func(ctx context.Context, app *App, args []string) error
}

// commands returns the full command table (spec section 12). Commands not
// implemented in this skeleton parse and validate their arguments, then
// return a clear not-implemented error naming the module that brings them.
func commands() []command {
	return []command{
		{"setup", "", "verify prerequisites and prepare the workspace/ directory", runSetup},
		{"status", "", "report repo root, workspace, prerequisites, and git branch", runStatus},
		{"reset", "--module <number>", "reset target repositories to a module starting checkpoint", runReset},
		{"start-lab", "<lab-id>", "prepare the starting state for a lab", runStartLab},
		{"validate", "<lab-id>", "run the validation checks for a lab", runValidate},
		{"run-task", "<task-id>", "execute a task from the task dataset", singleArgStub("run-task", "task-id", 2)},
		{"run-eval", "<evaluation-id>", "run an evaluation and collect its metrics", singleArgStub("run-eval", "evaluation-id", 8)},
		{"replay", "<run-id>", "replay a captured run from its stored trace", singleArgStub("replay", "run-id", 2)},
		{"inspect-trace", "<run-id>", "print the structured trace of a run", singleArgStub("inspect-trace", "run-id", 2)},
		{"cleanup", "", "remove temporary worktrees and stale lab state", noArgStub("cleanup", 3)},
		{"version", "", "print version, commit, and build date", runVersion},
	}
}

func (a *App) printUsage(w io.Writer) {
	fmt.Fprintln(w, "coursectl - course control utility for AI-Native Software Engineering")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Usage: coursectl <command> [arguments]")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Commands:")
	for _, c := range commands() {
		left := c.name
		if c.argHint != "" {
			left += " " + c.argHint
		}
		fmt.Fprintf(w, "  %-28s %s\n", left, c.summary)
	}
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Flags: --version prints the version; --help prints this text.")
}

// notImplemented is the shared error for skeleton commands. It is explicit
// on purpose: the tool never fakes behavior it does not have.
func notImplemented(what string, module int) error {
	return fmt.Errorf("%s is not implemented in this skeleton; it arrives with module %d of the course", what, module)
}

// singleArgStub returns a runner that requires exactly one positional
// argument and then reports the command as not implemented.
func singleArgStub(name, argName string, module int) func(context.Context, *App, []string) error {
	return func(_ context.Context, _ *App, args []string) error {
		if len(args) != 1 || args[0] == "" || strings.HasPrefix(args[0], "-") {
			return fmt.Errorf("usage: coursectl %s <%s>", name, argName)
		}
		return notImplemented(fmt.Sprintf("%s %s", name, args[0]), module)
	}
}

// noArgStub returns a runner that requires no arguments and then reports
// the command as not implemented.
func noArgStub(name string, module int) func(context.Context, *App, []string) error {
	return func(_ context.Context, _ *App, args []string) error {
		if len(args) != 0 {
			return fmt.Errorf("usage: coursectl %s", name)
		}
		return notImplemented(name, module)
	}
}

func runVersion(_ context.Context, app *App, args []string) error {
	if len(args) != 0 {
		return fmt.Errorf("usage: coursectl version")
	}
	fmt.Fprintln(app.Stdout, version.String())
	return nil
}

func runReset(ctx context.Context, app *App, args []string) error {
	fs := flag.NewFlagSet("reset", flag.ContinueOnError)
	fs.SetOutput(app.Stderr)
	module := fs.Int("module", -1, "module number to reset to (0-10)")
	if err := fs.Parse(args); err != nil {
		return fmt.Errorf("parsing reset flags: %w", err)
	}
	if fs.NArg() != 0 {
		return fmt.Errorf("usage: coursectl reset --module <number> (unexpected argument %q)", fs.Arg(0))
	}
	if *module < 0 || *module > 10 {
		return fmt.Errorf("usage: coursectl reset --module <number> (module must be 0-10)")
	}

	root, err := workspace.FindRepoRoot(app.WorkDir)
	if err != nil {
		return fmt.Errorf("locating course repository root: %w", err)
	}
	// The module->revision map is the source of truth; targets are reset by
	// revision, never by tag (spec 17-18).
	cp, err := course.ModuleCheckpoint(root, *module)
	if err != nil {
		return fmt.Errorf("resolving module %d checkpoint: %w", *module, err)
	}
	fmt.Fprintf(app.Stdout, "Resetting module %d target %s to revision %s (eight-step reset, spec 18):\n",
		*module, cp.RepoName(), cp.Revision)
	if err := app.manager(root).Reset(ctx, cp.RepoName(), cp.Revision); err != nil {
		return fmt.Errorf("resetting module %d: %w", *module, err)
	}
	fmt.Fprintf(app.Stdout, "Module %d reset complete.\n", *module)
	return nil
}

func runSetup(ctx context.Context, app *App, args []string) error {
	if len(args) != 0 {
		return fmt.Errorf("usage: coursectl setup")
	}

	fmt.Fprintln(app.Stdout, "Checking prerequisites (git, go, python):")
	missing := printPrereqs(ctx, app)
	if len(missing) > 0 {
		return fmt.Errorf("missing prerequisites: %s (install with the official native installer for your OS)", strings.Join(missing, ", "))
	}

	root, err := workspace.FindRepoRoot(app.WorkDir)
	if err != nil {
		return fmt.Errorf("locating course repository root: %w", err)
	}
	fmt.Fprintf(app.Stdout, "Course repository root: %s\n", root)

	ws, err := workspace.Ensure(root)
	if err != nil {
		return fmt.Errorf("preparing workspace directory: %w", err)
	}
	fmt.Fprintf(app.Stdout, "Workspace directory ready: %s (contents are gitignored)\n", ws)

	summary, err := course.ValidateModelConfig(root)
	if err != nil {
		return fmt.Errorf("validating model configuration: %w", err)
	}
	fmt.Fprintf(app.Stdout, "  %s\n", summary)

	repos, err := course.TargetRepos(root)
	if err != nil {
		return fmt.Errorf("resolving target repositories: %w", err)
	}
	fmt.Fprintln(app.Stdout, "Cloning target repositories into workspace/ (from the checkpoint map):")
	mgr := app.manager(root)
	for _, cp := range repos {
		if err := mgr.Clone(ctx, cp.Repository, cp.Revision); err != nil {
			return fmt.Errorf("setting up %s: %w", cp.RepoName(), err)
		}
	}
	fmt.Fprintln(app.Stdout, "Setup complete. Run 'coursectl status' to review your environment.")
	return nil
}

func runStartLab(ctx context.Context, app *App, args []string) error {
	if len(args) != 1 || args[0] == "" || strings.HasPrefix(args[0], "-") {
		return fmt.Errorf("usage: coursectl start-lab <lab-id>")
	}
	labID := args[0]

	root, err := workspace.FindRepoRoot(app.WorkDir)
	if err != nil {
		return fmt.Errorf("locating course repository root: %w", err)
	}
	m, err := course.LoadManifest(root, labID)
	if err != nil {
		return fmt.Errorf("loading lab %q: %w", labID, err)
	}
	mgr := app.manager(root)
	repoName := m.RepoName()

	fmt.Fprintf(app.Stdout, "Preparing lab %s (%s) on target %s at revision %s:\n",
		m.ID, m.Title, repoName, m.StartingRevision)
	// Phase-3 labs work in the main clone; no per-lab worktree is required.
	if !mgr.Exists(repoName) {
		// Fresh clone lands directly on the lab's starting revision.
		fmt.Fprintln(app.Stdout, "  target clone missing; cloning it now")
		if err := mgr.Clone(ctx, m.Repository, m.StartingRevision); err != nil {
			return fmt.Errorf("cloning target for lab %s: %w", m.ID, err)
		}
	} else {
		// Preserve any prior student work before the restore's clean removes
		// it, then restore to this lab's starting revision (reset step 3).
		for _, sub := range []string{"reports", "traces"} {
			dest, saved, aerr := mgr.Archive(repoName, sub)
			if aerr != nil {
				return fmt.Errorf("preserving %s for lab %s: %w", sub, m.ID, aerr)
			}
			if saved {
				fmt.Fprintf(app.Stdout, "  preserved existing %s -> %s\n", sub, dest)
			}
		}
		if err := mgr.Restore(ctx, repoName, m.StartingRevision); err != nil {
			return fmt.Errorf("preparing lab %s: %w", m.ID, err)
		}
	}
	fmt.Fprintf(app.Stdout, "  fixtures loaded from tracked files at %s\n", m.StartingRevision[:12])
	fmt.Fprintf(app.Stdout, "Lab %s is ready in workspace/%s. Run 'coursectl validate %s' when done.\n",
		m.ID, repoName, m.ID)
	return nil
}

func runValidate(ctx context.Context, app *App, args []string) error {
	if len(args) != 1 || args[0] == "" || strings.HasPrefix(args[0], "-") {
		return fmt.Errorf("usage: coursectl validate <lab-id>")
	}
	labID := args[0]

	root, err := workspace.FindRepoRoot(app.WorkDir)
	if err != nil {
		return fmt.Errorf("locating course repository root: %w", err)
	}
	m, err := course.LoadManifest(root, labID)
	if err != nil {
		return fmt.Errorf("loading lab %q: %w", labID, err)
	}
	mgr := app.manager(root)
	repoName := m.RepoName()
	if !mgr.Exists(repoName) {
		return fmt.Errorf("target clone %s is missing; run 'coursectl start-lab %s' first", repoName, m.ID)
	}

	fmt.Fprintf(app.Stdout, "Validating lab %s in workspace/%s (visible checks only; hidden graders are not run):\n",
		m.ID, repoName)
	failed := 0
	for _, c := range m.VisibleValidation {
		switch c.Kind {
		case "command":
			out, runErr := mgr.RunValidation(ctx, repoName, c.Command)
			if runErr != nil {
				failed++
				fmt.Fprintf(app.Stdout, "  FAIL command: %s\n        %s\n", c.Command, indent(strings.TrimSpace(out)))
			} else {
				fmt.Fprintf(app.Stdout, "  ok   command: %s\n", c.Command)
			}
		default:
			// artifact and human-review checks cannot be verified mechanically.
			fmt.Fprintf(app.Stdout, "  --   %s (manual): %s\n", c.Kind, c.Description)
		}
	}
	if failed > 0 {
		return fmt.Errorf("lab %s: %d visible validation command(s) failed", m.ID, failed)
	}
	fmt.Fprintf(app.Stdout, "Lab %s: all visible validation commands passed.\n", m.ID)
	return nil
}

// indent prefixes each line of s so failing-command output is set off from the
// validation report.
func indent(s string) string {
	if s == "" {
		return "(no output)"
	}
	return strings.ReplaceAll(s, "\n", "\n        ")
}

func runStatus(ctx context.Context, app *App, args []string) error {
	if len(args) != 0 {
		return fmt.Errorf("usage: coursectl status")
	}

	root, err := workspace.FindRepoRoot(app.WorkDir)
	if err != nil {
		fmt.Fprintf(app.Stdout, "Repository root: not found (%v)\n", err)
	} else {
		fmt.Fprintf(app.Stdout, "Repository root: %s\n", root)
		if workspace.Exists(root) {
			fmt.Fprintf(app.Stdout, "Workspace:       %s (present)\n", filepath.Join(root, workspace.DirName))
		} else {
			fmt.Fprintln(app.Stdout, "Workspace:       missing (run 'coursectl setup')")
		}
		if branch, berr := app.gitBranch(ctx, root); berr != nil {
			fmt.Fprintf(app.Stdout, "Git branch:      unknown (%v)\n", berr)
		} else {
			fmt.Fprintf(app.Stdout, "Git branch:      %s\n", branch)
		}
	}

	fmt.Fprintln(app.Stdout, "Prerequisites:")
	printPrereqs(ctx, app)
	return nil
}

// printPrereqs prints one line per required tool and returns the names of
// the tools that failed the check.
func printPrereqs(ctx context.Context, app *App) []string {
	var missing []string
	for _, r := range app.Checker.Check(ctx, prereq.DefaultTools()) {
		if r.OK() {
			fmt.Fprintf(app.Stdout, "  ok   %-7s %s (%s)\n", r.Name, r.Version, r.Path)
		} else {
			fmt.Fprintf(app.Stdout, "  FAIL %-7s %v\n", r.Name, r.Err)
			missing = append(missing, r.Name)
		}
	}
	return missing
}

func (a *App) gitBranch(ctx context.Context, root string) (string, error) {
	if a.GitBranch != nil {
		return a.GitBranch(ctx, root)
	}
	out, err := exec.CommandContext(ctx, "git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD").Output()
	if err != nil {
		return "", fmt.Errorf("running git rev-parse: %w", err)
	}
	return strings.TrimSpace(string(out)), nil
}
