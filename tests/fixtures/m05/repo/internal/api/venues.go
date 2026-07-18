// Package api exposes the bookit platform HTTP endpoints.
package api

import (
	"github.com/ai-eng-bootcamps/bookit-platform-fixture/internal/directory"
)

// venuePath reports the directory URL path for a venue. The directory package
// owns the slug rule; the handler only routes the question to it.
func venuePath(name string) string {
	return "/venues/" + directory.Slug(name)
}
