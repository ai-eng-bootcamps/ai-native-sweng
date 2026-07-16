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

	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/prereq"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/version"
	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/workspace"
)

const orgURL = "https://github.com/ai-eng-bootcamps"

// targetRepos are the course target repositories cloned into workspace/
// (spec sections 10.2-10.5). They are cloned, never forked.
var targetRepos = []string{
	"ai-native-sweng-bookit",
	"ai-native-sweng-bookit-platform",
	"ai-native-sweng-minefield",
}

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
		{"start-lab", "<lab-id>", "prepare the starting state for a lab", singleArgStub("start-lab", "lab-id", 0)},
		{"validate", "<lab-id>", "run the validation checks for a lab", singleArgStub("validate", "lab-id", 0)},
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

func runReset(_ context.Context, app *App, args []string) error {
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
	// Reset restores target repositories by checkpoint revision
	// (spec sections 17-18), never by manually reversing changes.
	return notImplemented(fmt.Sprintf("reset --module %d", *module), 0)
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

	fmt.Fprintln(app.Stdout, "Target repository clones (planned):")
	for _, repo := range targetRepos {
		fmt.Fprintf(app.Stdout, "  will clone %s/%s into %s%c%s\n",
			orgURL, repo, workspace.DirName, filepath.Separator, repo)
	}
	fmt.Fprintln(app.Stdout, "NOTICE: the target repositories are not yet published; skipping the clone step.")
	fmt.Fprintln(app.Stdout, "Setup complete. Run 'coursectl status' to review your environment.")
	return nil
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
