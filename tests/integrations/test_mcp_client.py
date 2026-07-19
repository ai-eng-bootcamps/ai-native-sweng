"""Student-implemented tests for the hand-rolled stdio MCP client (Lessons 9.4-9.5).

The full protocol round-trip against the supplied local server -
initialize, tools/list, tools/call, and JSON-RPC errors - plus the policy-gated
consequential path (which routes through the Module 3 approval gate). These run a
real server subprocess offline at zero cost and fail against the scaffolding
stubs.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from anse_harness.approvals.gate import ApprovalGate, approve_all, reject_all
from anse_harness.integrations import (
    IntegrationRecorder,
    MCPToolCapability,
    StdioMCPClient,
    gated_tools_call,
)
from anse_harness.tracing import TraceWriter, read_trace

pytestmark = pytest.mark.student_impl

SERVER_COMMAND = [sys.executable, "-m", "anse_harness.tools.mcp_repo_server"]


@pytest.fixture
def client() -> Iterator[StdioMCPClient]:
    mcp_client = StdioMCPClient(SERVER_COMMAND)
    try:
        yield mcp_client
    finally:
        mcp_client.close()


def test_initialize_handshake(client: StdioMCPClient) -> None:
    reply = client.initialize()
    assert reply["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in reply["result"]["capabilities"]
    assert reply["result"]["serverInfo"]["name"] == "mcp-repo-server"


def test_tools_list_discovers_repo_search(client: StdioMCPClient) -> None:
    client.initialize()
    reply = client.tools_list()
    tools = reply["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["repo_search"]
    assert "inputSchema" in tools[0]


def test_tools_call_is_deterministic(client: StdioMCPClient) -> None:
    client.initialize()
    first = client.tools_call("repo_search", {"query": "Normalize"})
    second = client.tools_call("repo_search", {"query": "Normalize"})
    text = first["result"]["content"][0]["text"]
    assert "normalize.go" in text
    assert second["result"]["content"][0]["text"] == text
    no_match = client.tools_call("repo_search", {"query": "zzz-no-such-symbol"})
    assert "no matches" in no_match["result"]["content"][0]["text"]


def test_json_rpc_errors(client: StdioMCPClient) -> None:
    client.initialize()
    unknown_tool = client.tools_call("delete_repo", {"query": "x"})
    missing_arg = client.tools_call("repo_search", {})
    unknown_method = client._rpc("resources/list")
    assert unknown_tool["error"]["code"] == -32602
    assert missing_arg["error"]["code"] == -32602
    assert unknown_method is not None and unknown_method["error"]["code"] == -32601


def test_notifications_carry_no_id_and_expect_no_reply(client: StdioMCPClient) -> None:
    # A notification returns None and does not consume a reply line, so the next
    # request still lines up with its own response.
    client.initialize()
    assert client._rpc("notifications/initialized", notify=True) is None
    listed = client.tools_list()
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["repo_search"]


def test_gated_read_only_call_end_to_end(client: StdioMCPClient, tmp_path: Path) -> None:
    client.initialize()
    trace = tmp_path / "mcp.jsonl"
    with TraceWriter(trace) as writer:
        recorder = IntegrationRecorder(writer, "run", "wf")
        reply = gated_tools_call(
            client,
            MCPToolCapability("repo_search", side_effect_class=0),
            {"query": "Normalize"},
            gate=ApprovalGate(reject_all),  # class 0 never asks, so a reject resolver is irrelevant
            recorder=recorder,
        )
    assert "normalize.go" in reply["result"]["content"][0]["text"]
    types = [event.event_type for event in read_trace(trace)]
    assert types == ["policy_evaluated", "tool_requested", "tool_completed"]


def _fake_caller_call_log() -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Fake:
        def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            calls.append((name, arguments))
            return {"jsonrpc": "2.0", "id": 1, "result": {"content": [], "isError": False}}

    return _Fake(), calls


def test_gated_consequential_call_requires_approval_and_reject_blocks(tmp_path: Path) -> None:
    caller, calls = _fake_caller_call_log()
    trace = tmp_path / "mcp.jsonl"
    with TraceWriter(trace) as writer:
        recorder = IntegrationRecorder(writer, "run", "wf")
        with pytest.raises(PermissionError):
            gated_tools_call(
                caller,
                MCPToolCapability("apply_change", side_effect_class=4),
                {},
                gate=ApprovalGate(reject_all),
                recorder=recorder,
            )
    types = [event.event_type for event in read_trace(trace)]
    assert types == ["policy_evaluated", "approval_requested", "approval_resolved", "tool_failed"]
    assert calls == []


def test_gated_consequential_call_proceeds_when_approved() -> None:
    caller, calls = _fake_caller_call_log()
    recorder = IntegrationRecorder(None, "run", "wf")
    gated_tools_call(
        caller,
        MCPToolCapability("apply_change", side_effect_class=4),
        {},
        gate=ApprovalGate(approve_all),
        recorder=recorder,
    )
    assert calls == [("apply_change", {})]
