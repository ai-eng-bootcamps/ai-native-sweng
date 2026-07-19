"""Supplied-infrastructure tests for the Module 9 integration scaffolding.

These exercise the parts students consume as-is - the typed contracts, the
offline double, the MCP server, the audit and protocol-decision artifacts, the
recorder, the credential-redaction backstop, the draft-only surface guard, and
the zero-dependency rule. They pass against the scaffolding stubs (they never
call a student-implemented adapter or client method) and stay in the default run.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from anse_harness.approvals.gate import ApprovalGate, reject_all
from anse_harness.integrations import (
    AUDIT_OUTCOMES,
    INTEGRATION_ACTIONS,
    PROTOCOL_JUSTIFICATIONS,
    PROTOCOL_OPTIONS,
    ExternalActionAudit,
    GitHubAdapter,
    IntegrationError,
    IntegrationRecorder,
    IntegrationRequest,
    LocalGitHubDouble,
    MCPToolCapability,
    ProtocolDecisionRecord,
    audit_artifact_id,
    draft_pr_from_workflow_result,
    gated_tools_call,
    github_token_from_env,
)
from anse_harness.integrations import contracts as contracts_module
from anse_harness.integrations import github as github_module
from anse_harness.integrations import local_double as local_double_module
from anse_harness.integrations import mcp_client as mcp_client_module
from anse_harness.tools import mcp_repo_server
from anse_harness.tracing import TraceEvent, TraceWriter, read_trace, redact_event

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m09"


def _double() -> LocalGitHubDouble:
    return LocalGitHubDouble.from_fixtures(FIXTURES)


# --- contracts -------------------------------------------------------------


def test_integration_request_payload_omits_body_and_credentials() -> None:
    request = IntegrationRequest(
        "create_draft_pr", "POST", "/pulls", {"title": "x", "draft": True}, idempotency_key="idem-1"
    )
    payload = request.to_payload()
    assert payload == {
        "action": "create_draft_pr",
        "method": "POST",
        "path": "/pulls",
        "idempotency_key": "idem-1",
    }
    assert "body" not in payload


def test_integration_actions_are_read_plus_draft_only() -> None:
    assert INTEGRATION_ACTIONS == ("read_issue", "read_ci_status", "create_draft_pr")
    for forbidden in ("merge", "push", "create_release", "deploy", "merge_pull_request"):
        assert forbidden not in INTEGRATION_ACTIONS


def test_external_action_audit_round_trip_and_id() -> None:
    audit = ExternalActionAudit(
        action="create_draft_pr",
        method="POST",
        path="/pulls",
        idempotency_key="idem-abc",
        approved=True,
        outcome="completed",
        status=201,
    )
    payload = audit.to_payload()
    assert payload["artifact_type"] == "external_action_audit"
    assert payload["artifact_id"] == "audit-create_draft_pr-idem-abc"
    assert audit_artifact_id("read_issue", None) == "audit-read_issue-read"
    assert ExternalActionAudit.from_payload(payload) == audit


def test_external_action_audit_rejects_unknown_outcome() -> None:
    assert "completed" in AUDIT_OUTCOMES
    with pytest.raises(ValueError):
        ExternalActionAudit(
            action="x",
            method="POST",
            path="/p",
            idempotency_key=None,
            approved=True,
            outcome="merged",
        )


# --- protocol-decision record (Evidence Gate 5) ----------------------------


def test_committed_protocol_decision_record_validates() -> None:
    import json

    payload = json.loads((FIXTURES / "protocol_decision_record.json").read_text(encoding="utf-8"))
    record = ProtocolDecisionRecord.from_payload(payload)
    assert record.chosen in PROTOCOL_OPTIONS
    assert record.justifications
    for justification in record.justifications:
        assert justification in PROTOCOL_JUSTIFICATIONS


def test_protocol_record_requires_justification_for_a_non_local_choice() -> None:
    with pytest.raises(ValueError):
        ProtocolDecisionRecord(
            capability="c", chosen="mcp", justifications=(), rejected_alternatives=(), rationale="r"
        ).validate()
    # A local interface needs no protocol justification.
    ProtocolDecisionRecord(
        capability="c",
        chosen="direct_function_call",
        justifications=(),
        rejected_alternatives=(),
        rationale="in-process, single owner, no interoperability requirement",
    ).validate()


def test_protocol_record_rejects_unknown_vocabulary() -> None:
    with pytest.raises(ValueError):
        ProtocolDecisionRecord(
            capability="c",
            chosen="grpc",
            justifications=(),
            rejected_alternatives=(),
            rationale="r",
        ).validate()
    with pytest.raises(ValueError):
        ProtocolDecisionRecord(
            capability="c",
            chosen="mcp",
            justifications=("it_is_cool",),
            rejected_alternatives=(),
            rationale="r",
        ).validate()


# --- local double ----------------------------------------------------------


def test_double_reads_fixture_issue_and_ci() -> None:
    double = _double()
    issue = double.send(IntegrationRequest("read_issue", "GET", "/issues/7", {"number": 7}))
    assert issue.data["number"] == 7
    ci = double.send(
        IntegrationRequest(
            "read_ci_status", "GET", "/commits/feature/healthz/status", {"ref": "feature/healthz"}
        )
    )
    assert ci.data["state"] == "success"


def test_double_missing_issue_is_a_non_retryable_error() -> None:
    with pytest.raises(IntegrationError) as excinfo:
        _double().send(IntegrationRequest("read_issue", "GET", "/issues/999", {"number": 999}))
    assert excinfo.value.retryable is False


def test_double_refuses_a_non_draft_create() -> None:
    double = _double()
    with pytest.raises(IntegrationError) as excinfo:
        double.send(
            IntegrationRequest(
                "create_draft_pr", "POST", "/pulls", {"draft": False}, idempotency_key="k"
            )
        )
    assert excinfo.value.retryable is False
    assert double.created_prs == {}


def test_double_deduplicates_by_idempotency_key() -> None:
    double = _double()
    request = IntegrationRequest(
        "create_draft_pr", "POST", "/pulls", {"draft": True, "title": "t"}, idempotency_key="k"
    )
    first = double.send(request)
    second = double.send(request)
    assert first.data["number"] == second.data["number"]
    assert first.data["deduped"] is False
    assert second.data["deduped"] is True
    assert len(double.created_prs) == 1


def test_double_timeout_lever_raises_retryable() -> None:
    double = _double()
    double.raise_timeout = True
    with pytest.raises(IntegrationError) as excinfo:
        double.send(IntegrationRequest("read_issue", "GET", "/issues/7", {"number": 7}))
    assert excinfo.value.retryable is True


# --- MCP server (pure handler) ---------------------------------------------


def test_mcp_server_initialize_and_discovery() -> None:
    init = mcp_repo_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init is not None
    assert init["result"]["protocolVersion"] == mcp_repo_server.PROTOCOL_VERSION
    assert init["result"]["serverInfo"]["name"] == "mcp-repo-server"
    assert mcp_repo_server.handle({"method": "notifications/initialized"}) is None
    listed = mcp_repo_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed is not None
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["repo_search"]


def test_mcp_server_tool_call_is_deterministic() -> None:
    call = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "repo_search", "arguments": {"query": "Normalize"}},
    }
    first = mcp_repo_server.handle(call)
    second = mcp_repo_server.handle(call)
    assert first is not None and second is not None
    assert first["result"]["content"][0]["text"] == second["result"]["content"][0]["text"]
    assert "normalize.go" in first["result"]["content"][0]["text"]


def test_mcp_server_errors() -> None:
    unknown_tool = mcp_repo_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }
    )
    missing_arg = mcp_repo_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "repo_search", "arguments": {}},
        }
    )
    unknown_method = mcp_repo_server.handle({"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
    assert unknown_tool is not None and unknown_tool["error"]["code"] == -32602
    assert missing_arg is not None and missing_arg["error"]["code"] == -32602
    assert unknown_method is not None and unknown_method["error"]["code"] == -32601


# --- draft-only surface guard (the safety regression test) -----------------


def test_adapter_surface_is_exactly_read_plus_draft_pr() -> None:
    """FAILS if a merge/push/release/deploy method is ever added to the adapter."""
    public_methods = {name for name in dir(GitHubAdapter) if not name.startswith("_")}
    assert public_methods == {"read_issue", "read_ci_status", "create_draft_pr"}
    for forbidden in (
        "merge",
        "merge_pull_request",
        "push",
        "create_release",
        "deploy",
        "delete_branch",
    ):
        assert not hasattr(GitHubAdapter, forbidden)


# --- recorder + credential redaction backstop ------------------------------


def test_recorder_assigns_sequential_namespaced_ids() -> None:
    events: list[TraceEvent] = []

    class _Capture:
        def write(self, event: TraceEvent) -> None:
            events.append(event)

    recorder = IntegrationRecorder(_Capture(), "run-x", "wf-x")  # type: ignore[arg-type]
    first = recorder.emit("tool_requested", "integration.github", {"a": 1}, status="requested")
    second = recorder.emit("tool_completed", "integration.github", {"a": 2})
    assert (first, second) == ("evt-int-0000", "evt-int-0001")
    assert [event.event_id for event in events] == ["evt-int-0000", "evt-int-0001"]


def test_sensitive_key_redaction_scrubs_a_leaked_token() -> None:
    event = TraceEvent(
        run_id="r",
        workflow_id="w",
        component="integration.github",
        event_type="tool_requested",
        status="requested",
        payload={"authorization": "ghp_SECRET_should_be_scrubbed", "action": "create_draft_pr"},
        sensitive_keys=("authorization",),
    )
    scrubbed = redact_event(event)
    assert scrubbed.payload["authorization"] == "[REDACTED]"
    assert scrubbed.payload["action"] == "create_draft_pr"


def test_github_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANSE_TEST_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        github_token_from_env("ANSE_TEST_TOKEN")
    monkeypatch.setenv("ANSE_TEST_TOKEN", "ghp_env_value")
    assert github_token_from_env("ANSE_TEST_TOKEN") == "ghp_env_value"


# --- gated MCP call (supplied composition over the frozen approval gate) ----


class _FakeCaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": [], "isError": False}}


def test_gated_call_read_only_allows_without_approval(tmp_path: Path) -> None:
    caller = _FakeCaller()
    with TraceWriter(tmp_path / "t.jsonl") as writer:
        recorder = IntegrationRecorder(writer, "run", "wf")
        gated_tools_call(
            caller,
            MCPToolCapability("repo_search", side_effect_class=0),
            {"query": "x"},
            gate=ApprovalGate(reject_all),  # would reject, but class 0 never asks
            recorder=recorder,
        )
    types = [event.event_type for event in read_trace(tmp_path / "t.jsonl")]
    assert types == ["policy_evaluated", "tool_requested", "tool_completed"]
    assert caller.calls == [("repo_search", {"query": "x"})]


# --- gated PrepareResult hook: the platform=None no-op ----------------------


def test_draft_pr_hook_is_a_no_op_when_platform_is_none() -> None:
    class _Result:
        patch = "--- a\n+++ b\n"

    assert (
        draft_pr_from_workflow_result(
            _Result(),
            platform=None,
            task_id="t",
            workflow_id="w",
            artifact_version="v1",
            title="x",
            head="h",
            base="main",
        )
        is None
    )


# --- zero-dependency rule --------------------------------------------------


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_committed_traces_are_credential_free_and_use_frozen_event_types() -> None:
    from anse_harness.tracing.events import EVENT_TYPES

    traces = Path(__file__).resolve().parents[2] / "traces" / "m09"
    for name in ("integration_run.jsonl", "mcp_session.jsonl"):
        text = (traces / name).read_text(encoding="utf-8")
        assert "ghp_" not in text
        assert "Authorization" not in text
        assert "Bearer" not in text
        for event in read_trace(traces / name):
            # External actions appear in traces via the existing tool_* vocabulary;
            # the frozen event set is not extended (no integration_* types).
            assert event.event_type in EVENT_TYPES
            assert not event.event_type.startswith("integration_")


def test_integration_code_imports_only_stdlib_and_anse_harness() -> None:
    stdlib = {
        "__future__",
        "json",
        "os",
        "sys",
        "subprocess",
        "urllib",
        "hashlib",
        "dataclasses",
        "typing",
        "pathlib",
        "collections",
        "enum",
    }
    modules = [
        Path(contracts_module.__file__),
        Path(local_double_module.__file__),
        Path(github_module.__file__),
        Path(mcp_client_module.__file__),
        Path(mcp_repo_server.__file__),
    ]
    third_party: set[str] = set()
    for module_path in modules:
        for name in _top_level_imports(module_path):
            if name in stdlib or name == "anse_harness":
                continue
            third_party.add(name)
    assert third_party == set(), f"unexpected third-party imports: {sorted(third_party)}"
