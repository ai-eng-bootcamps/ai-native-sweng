"""JSONL trace writer and reader (spec 7.13, 19).

One trace file holds one run: one JSON object per line, each a serialized
TraceEvent. The writer redacts payload values whose keys are listed in an
event's sensitive_keys before writing, so classified values never reach disk.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any

from anse_harness.tracing.events import TraceEvent

REDACTED = "[REDACTED]"


def _redact_value(value: Any, keys: frozenset[str]) -> Any:
    """Recursively replace values of any dict key in `keys` with REDACTED."""
    if isinstance(value, dict):
        return {k: (REDACTED if k in keys else _redact_value(v, keys)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, keys) for item in value]
    return value


def redact_event(event: TraceEvent) -> TraceEvent:
    """Return a copy of the event with sensitive payload values redacted."""
    if not event.sensitive_keys:
        return event
    keys = frozenset(event.sensitive_keys)
    return replace(event, payload=_redact_value(event.payload, keys))


class TraceWriter:
    """Appends trace events to a JSONL file, redacting sensitive payload values."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8")

    def write(self, event: TraceEvent) -> None:
        line = json.dumps(redact_event(event).to_dict(), sort_keys=True)
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_trace(path: Path) -> list[TraceEvent]:
    """Read all events from a JSONL trace file, in order."""
    events: list[TraceEvent] = []
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON in trace file") from exc
            events.append(TraceEvent.from_dict(data))
    return events
