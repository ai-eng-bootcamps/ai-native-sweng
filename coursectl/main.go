// Command coursectl is the course control utility for the AI-Native
// Software Engineering course. It is the primary operational interface for
// students on macOS, Linux, and Windows: setup, status, resets, labs,
// tasks, evaluations, and trace inspection all go through it.
//
// Students never compile this tool; CI publishes prebuilt static binaries
// via GitHub Releases and the thin bootstrap wrappers in scripts/ fetch the
// right one.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"

	"github.com/ai-eng-bootcamps/ai-native-sweng/coursectl/internal/cli"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	if err := cli.Run(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintf(os.Stderr, "coursectl: %v\n", err)
		os.Exit(1)
	}
}
