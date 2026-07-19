"""A minimal local MCP server over stdio (standard library only; Lesson 9.5).

Speaks newline-delimited JSON-RPC 2.0 on stdin/stdout - the MCP stdio transport -
and exposes ONE software-engineering capability: ``repo_search`` over a fixed
in-repo fixture (standing in for Module 4 repository intelligence over a clone).
It is deterministic (the same query yields the same result), needs no network,
and costs nothing to run, so the client round-trip is exercisable offline.

This server ships in the public repository as student-visible infrastructure:
building a custom MCP server is optional in the core course (blueprint), so the
course supplies one to consume. Diagnostics must go to stderr; stdout carries
only the protocol stream, so a stray print there would corrupt it.

Run as a subprocess: ``python -m anse_harness.tools.mcp_repo_server``.

SCAFFOLDING: supplied. Students consume this server through the MCP client.
"""

from __future__ import annotations

import json
import sys
from typing import Any

PROTOCOL_VERSION = "2024-11-05"

#: The fixture "repository": path -> file lines. A real server would search a clone.
FIXTURE: dict[str, list[str]] = {
    "internal/textproc/normalize.go": [
        "func NormalizeWhitespace(input string) string {",
        '  return strings.Join(strings.Fields(input), " ")',
    ],
    "internal/textproc/normalize_test.go": [
        "func TestNormalizeWhitespace(t *testing.T) {",
        "  // collapses runs of internal whitespace",
    ],
    "README.md": ["# textproc", "A small text-processing library."],
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "repo_search",
        "description": "Search repository file contents for a substring.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
]


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _repo_search(query: str) -> dict[str, Any]:
    hits: list[str] = []
    for path, lines in FIXTURE.items():
        for index, line in enumerate(lines, start=1):
            if query in line:
                hits.append(f"{path}:{index}: {line.strip()}")
    text = "\n".join(hits) if hits else f"no matches for {query!r}"
    return {"content": [{"type": "text", "text": text}], "isError": False}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message; return the reply, or None for a notification."""
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-repo-server", "version": "0.0.1"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name != "repo_search":
            return _error(request_id, -32602, f"unknown tool: {name}")
        if "query" not in arguments:
            return _error(request_id, -32602, "missing required argument: query")
        return _result(request_id, _repo_search(arguments["query"]))
    return _error(request_id, -32601, f"method not found: {method}")


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            sys.stdout.flush()
            continue
        reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
