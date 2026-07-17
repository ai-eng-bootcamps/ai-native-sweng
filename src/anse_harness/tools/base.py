"""Typed tool contract and a minimal registry (canonical-reference.md section 11).

A tool is the only way a worker touches the world outside the model. Every tool
declares a stable, typed contract - a name, a human-readable description, a JSON
input schema, and a side-effect class (canonical-reference.md section 6) - and
returns a structured ``ToolResult`` rather than a bare string, so the loop and
the trace can record what happened without parsing prose.

SCAFFOLDING: the data contracts below are supplied; the registry behaviour is
yours to implement in Module 2, Lesson 2.1 ("From model call to tool loop").
Replace each ``raise NotImplementedError`` with a working body.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from anse_harness.models.types import ToolSpec


class ToolError(Exception):
    """Base class for tool-contract failures (unknown tool, invalid arguments)."""


class UnknownToolError(ToolError):
    """The model requested a tool that is not registered."""


class ToolResult:
    """The structured outcome of one tool invocation.

    ``output`` is the observation folded back into the conversation. ``ok`` is
    ``False`` when the tool ran but could not satisfy the request (for example a
    denied path); ``error`` then carries a short, model-readable reason.
    """

    __slots__ = ("output", "ok", "error")

    def __init__(self, output: str, *, ok: bool = True, error: str | None = None) -> None:
        self.output = output
        self.ok = ok
        self.error = error

    def __repr__(self) -> str:
        return f"ToolResult(ok={self.ok!r}, error={self.error!r}, output_len={len(self.output)})"


class Tool(ABC):
    """A typed, read-or-write capability the model may invoke through the loop."""

    #: Stable identifier the model calls (matches ``ToolCall.name``).
    name: ClassVar[str]
    #: One-line description shown to the model.
    description: ClassVar[str]
    #: JSON schema for the tool's ``arguments`` object.
    input_schema: ClassVar[dict[str, Any]]
    #: Side-effect class from canonical-reference.md section 6 (0 = observation only).
    side_effect_class: ClassVar[int]

    @abstractmethod
    def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the tool for one model-supplied ``arguments`` object."""

    def to_spec(self) -> ToolSpec:
        """Serialize this tool's contract into the request-side ``ToolSpec``."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )


class ToolRegistry:
    """Stores the tools available to a worker, keyed by name, in insertion order.

    Insertion order must be preserved so the tool list handed to the model is
    deterministic across runs - a precondition for replay conformance.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add a tool. Re-registering the same name is a programming error."""
        raise NotImplementedError(
            "Module 2, Lesson 2.1: store the tool by name; reject a duplicate name."
        )

    def get(self, name: str) -> Tool:
        """Return the registered tool, or raise ``UnknownToolError``."""
        raise NotImplementedError(
            "Module 2, Lesson 2.1: look up the tool; raise UnknownToolError if absent."
        )

    def specs(self) -> list[ToolSpec]:
        """Return the request-side specs for every tool, in registration order."""
        raise NotImplementedError(
            "Module 2, Lesson 2.1: return each registered tool's to_spec(), in order."
        )
