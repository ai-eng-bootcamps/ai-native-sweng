"""Hand-rolled stdio MCP client and the policy-gated tool-call path (Lessons 9.4, 9.5).

MCP (the Model Context Protocol) is one protocol for model-to-tool and context
integration. This client speaks newline-delimited JSON-RPC 2.0 over a server
subprocess's stdin/stdout - the MCP stdio transport - using only the standard
library (``subprocess`` + ``json``). There is no SDK and no dependency: the point
is to teach the protocol, and a hand-rolled client is a zero-dependency way to do
that (the framework/SDK translation is Lesson 9.7 prose, not code).

An MCP tool call is a tool call. ``gated_tools_call`` routes one through the same
approval boundary as any other tool, gated by the capability's side-effect class
(canonical §6): a read-only capability is allowed without approval; a
consequential one requires it. There is no special casing.

SCAFFOLDING: the subprocess transport (``__init__``, ``close``, ``_send_line``,
``_read_line``), ``MCPToolCapability``, and ``gated_tools_call`` are supplied.
Implement the JSON-RPC core (``_rpc``) and the three MCP operations
(``initialize``, ``tools_list``, ``tools_call``) in Module 9, Lessons 9.4-9.5.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from anse_harness.approvals.gate import ApprovalDecision, ApprovalGate, ApprovalRequest
from anse_harness.integrations.contracts import IntegrationRecorder

#: The component name every MCP trace event carries.
COMPONENT = "integration.mcp"

#: The MCP protocol version this client and the supplied server speak.
PROTOCOL_VERSION = "2024-11-05"


class StdioMCPClient:
    """A minimal MCP client over a server subprocess's stdio pipes."""

    def __init__(self, server_command: list[str]) -> None:
        self._process = subprocess.Popen(
            server_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def _send_line(self, message: dict[str, Any]) -> None:
        """Write one JSON-RPC message as a single newline-terminated line."""
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def _read_line(self) -> dict[str, Any]:
        """Read and parse one JSON-RPC reply line; raise if the server closed."""
        assert self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed the stream before replying")
        parsed: dict[str, Any] = json.loads(line)
        return parsed

    def _rpc(
        self, method: str, params: dict[str, Any] | None = None, *, notify: bool = False
    ) -> dict[str, Any] | None:
        """Send one JSON-RPC 2.0 request (or notification) and return the reply.

        A notification carries no ``id`` and expects no reply; a request carries a
        monotonically increasing ``id`` and returns the parsed reply object.
        """
        raise NotImplementedError(
            "Module 9, Lesson 9.4: build {'jsonrpc': '2.0', 'method': method}; when "
            "not notify, increment self._id and set 'id'; include 'params' when given; "
            "_send_line it; when notify return None, otherwise return _read_line()."
        )

    def initialize(self) -> dict[str, Any]:
        """Perform the MCP initialize handshake (Lesson 9.5).

        Send ``initialize`` with the client's protocol version and capabilities,
        then the ``notifications/initialized`` notification, and return the
        server's initialize result.
        """
        raise NotImplementedError(
            "Module 9, Lesson 9.5: _rpc('initialize', {'protocolVersion': "
            "PROTOCOL_VERSION, 'capabilities': {}, 'clientInfo': {...}}); then "
            "_rpc('notifications/initialized', notify=True); return the reply."
        )

    def tools_list(self) -> dict[str, Any]:
        """Discover the server's tools (Lesson 9.5): return the ``tools/list`` reply."""
        raise NotImplementedError("Module 9, Lesson 9.5: return _rpc('tools/list').")

    def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke one tool (Lesson 9.5): return the ``tools/call`` reply (which may
        carry a JSON-RPC ``error`` for an unknown tool or a missing argument)."""
        raise NotImplementedError(
            "Module 9, Lesson 9.5: return _rpc('tools/call', {'name': name, "
            "'arguments': arguments})."
        )

    def close(self) -> None:
        """Close stdin and terminate the server subprocess."""
        if self._process.stdin is not None:
            self._process.stdin.close()
        self._process.terminate()
        self._process.wait(timeout=5)

    def __enter__(self) -> StdioMCPClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class ToolCaller(Protocol):
    """The one client operation ``gated_tools_call`` needs."""

    def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MCPToolCapability:
    """One MCP tool and its side-effect class (canonical §6), for policy gating."""

    tool_name: str
    side_effect_class: int


def gated_tools_call(
    client: ToolCaller,
    capability: MCPToolCapability,
    arguments: dict[str, Any],
    *,
    gate: ApprovalGate,
    recorder: IntegrationRecorder,
    server_id: str = "mcp-repo-server",
) -> dict[str, Any]:
    """Call an MCP tool through the approval boundary, gated by side-effect class.

    A read-only capability (class 0) is allowed without approval; a consequential
    one (class >= 3) requires it. Every step is traced with the existing
    ``tool_*``/``policy_evaluated``/``approval_*`` vocabulary - an MCP call is a
    tool call, nothing more.
    """
    requires_approval = capability.side_effect_class >= 3
    recorder.emit(
        "policy_evaluated",
        COMPONENT,
        {
            "server": server_id,
            "tool": capability.tool_name,
            "side_effect_class": capability.side_effect_class,
            "decision": "require_approval" if requires_approval else "allow",
        },
    )
    if requires_approval:
        recorder.emit(
            "approval_requested",
            COMPONENT,
            {"action": f"mcp:{capability.tool_name}", "server": server_id},
        )
        decision = gate.request(
            ApprovalRequest(
                action=f"mcp:{capability.tool_name}",
                reason=f"call {capability.tool_name} on {server_id}",
                risk=f"external (class {capability.side_effect_class})",
            )
        )
        recorder.emit(
            "approval_resolved", COMPONENT, {"decision": decision.value}, status=decision.value
        )
        if decision != ApprovalDecision.APPROVED:
            recorder.emit(
                "tool_failed",
                COMPONENT,
                {"tool": capability.tool_name, "decision": decision.value},
                status="rejected",
            )
            raise PermissionError(
                f"MCP call {capability.tool_name!r} not approved: {decision.value}"
            )
    request_id = recorder.emit(
        "tool_requested",
        COMPONENT,
        {"server": server_id, "tool": capability.tool_name, "arguments": arguments},
        status="requested",
    )
    reply = client.tools_call(capability.tool_name, arguments)
    recorder.emit(
        "tool_completed",
        COMPONENT,
        {"server": server_id, "tool": capability.tool_name, "is_error": "error" in reply},
        parent_event_id=request_id,
    )
    return reply
