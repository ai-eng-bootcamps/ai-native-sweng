"""Security tests: the trace writer never logs values marked sensitive (spec 7.16, 19, 22)."""

from pathlib import Path

from anse_harness.tracing import REDACTED, TraceEvent, TraceWriter, read_trace

SECRET = "sk-live-EXTREMELY-SECRET-VALUE-12345"


def _sensitive_event() -> TraceEvent:
    return TraceEvent(
        run_id="run-1",
        workflow_id="wf-1",
        component="integrations",
        event_type="tool_requested",
        status="ok",
        payload={
            "tool": "github_create_pr",
            "request": {"api_key": SECRET, "repo": "example/repo"},
            "attempts": [{"api_key": SECRET, "outcome": "denied"}],
        },
        sensitivity="sensitive",
        sensitive_keys=("api_key",),
    )


def test_sensitive_values_never_reach_disk(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    with TraceWriter(path) as writer:
        writer.write(_sensitive_event())

    raw = path.read_text(encoding="utf-8")
    assert SECRET not in raw
    assert REDACTED in raw


def test_redaction_applies_at_any_nesting_depth(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    with TraceWriter(path) as writer:
        writer.write(_sensitive_event())

    (event,) = read_trace(path)
    assert event.payload["request"]["api_key"] == REDACTED
    assert event.payload["attempts"][0]["api_key"] == REDACTED
    # Non-sensitive values survive untouched.
    assert event.payload["request"]["repo"] == "example/repo"
    assert event.sensitivity == "sensitive"
