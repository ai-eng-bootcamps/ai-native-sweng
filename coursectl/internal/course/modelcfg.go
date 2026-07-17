package course

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// modelConfigPath is the default model configuration, relative to the course
// root. The authoritative parser is the Python harness
// (src/anse_harness/models/factory.py); coursectl performs the same essential
// checks so setup fails fast on a broken configuration.
const modelConfigPath = "configs/models/default.toml"

var validModes = map[string]bool{"live": true, "scripted": true, "replay": true}

// ValidateModelConfig checks that the default model configuration selects a
// valid mode and that the file the mode depends on exists. It returns a short
// human-readable summary on success. This is a lightweight key scan, not a
// full TOML parser: default.toml is flat with one value per line.
func ValidateModelConfig(root string) (string, error) {
	p := filepath.Join(root, modelConfigPath)
	f, err := os.Open(p)
	if err != nil {
		return "", fmt.Errorf("opening model config %s: %w", p, err)
	}
	defer f.Close()

	var mode, script, trace, model string
	section := ""
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		key, val, ok := parseTOMLLine(scanner.Text(), &section)
		if !ok {
			continue
		}
		switch {
		case section == "" && key == "mode":
			mode = val
		case section == "scripted" && key == "script":
			script = val
		case section == "replay" && key == "trace":
			trace = val
		case section == "live" && key == "model":
			model = val
		}
	}
	if err := scanner.Err(); err != nil {
		return "", fmt.Errorf("reading model config %s: %w", p, err)
	}

	if !validModes[mode] {
		return "", fmt.Errorf("model config %s: mode must be live, scripted, or replay, got %q", p, mode)
	}
	base := filepath.Dir(p)
	switch mode {
	case "scripted":
		if script == "" {
			return "", fmt.Errorf("model config %s: scripted mode requires [scripted] script", p)
		}
		if err := mustExist(base, script); err != nil {
			return "", fmt.Errorf("model config %s: scripted %w", p, err)
		}
		return fmt.Sprintf("model config ok: mode=scripted, script=%s", script), nil
	case "replay":
		if trace == "" {
			return "", fmt.Errorf("model config %s: replay mode requires [replay] trace", p)
		}
		if err := mustExist(base, trace); err != nil {
			return "", fmt.Errorf("model config %s: replay %w", p, err)
		}
		return fmt.Sprintf("model config ok: mode=replay, trace=%s", trace), nil
	default: // live
		if model == "" {
			return "", fmt.Errorf("model config %s: live mode requires [live] model", p)
		}
		return fmt.Sprintf("model config ok: mode=live, model=%s", model), nil
	}
}

func mustExist(base, rel string) error {
	p := filepath.Join(base, rel)
	if _, err := os.Stat(p); err != nil {
		return fmt.Errorf("file %s not found: %w", rel, err)
	}
	return nil
}

// parseTOMLLine extracts a key/value from one line, tracking the current
// [section] header via the section pointer. It reports ok=false for blank
// lines, comments, and section headers.
func parseTOMLLine(line string, section *string) (key, val string, ok bool) {
	line = strings.TrimSpace(line)
	if i := strings.IndexByte(line, '#'); i >= 0 {
		line = strings.TrimSpace(line[:i])
	}
	if line == "" {
		return "", "", false
	}
	if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
		*section = strings.Trim(line, "[]")
		return "", "", false
	}
	eq := strings.IndexByte(line, '=')
	if eq < 0 {
		return "", "", false
	}
	key = strings.TrimSpace(line[:eq])
	val = strings.Trim(strings.TrimSpace(line[eq+1:]), `"`)
	return key, val, true
}
