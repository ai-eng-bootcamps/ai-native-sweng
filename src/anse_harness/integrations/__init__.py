"""External integrations: repository-platform and protocol adapters (Module 9, spec §16).

The integration boundary is where the harness reaches a system outside its
process and repository. Two ideas hold the module together:

* The **Transport seam** (``contracts``): the adapter does all the logic, shaping,
  gating, and audit; only the injected transport differs offline versus live. The
  offline transport is the deterministic ``LocalGitHubDouble``; the one
  network-touching transport is ``github.LiveHTTPTransport`` and it never runs in
  tests. Integration determinism comes from the double, not from model replay.
* **Safety by absence, boundary, and approval**: the adapter surface is
  read-plus-draft-PR only (no merge/push/release/deploy method exists); ``draft``
  is hard-coded and the boundary refuses non-draft creates; every consequential
  action routes through the Module 3 approval gate. Credentials come from the
  environment and never enter a payload, an audit record, or a trace.

The MCP client (``mcp_client``) and the supplied local server
(``anse_harness.tools.mcp_repo_server``) teach the protocol with a hand-rolled,
zero-dependency stdio JSON-RPC round-trip.
"""

from anse_harness.integrations.contracts import (
    AUDIT_OUTCOMES,
    INTEGRATION_ACTIONS,
    LOCAL_PROTOCOL_OPTIONS,
    PROTOCOL_JUSTIFICATIONS,
    PROTOCOL_OPTIONS,
    ExternalActionAudit,
    IntegrationCancelledError,
    IntegrationError,
    IntegrationRecorder,
    IntegrationRequest,
    IntegrationResponse,
    ProtocolDecisionRecord,
    Transport,
    audit_artifact_id,
)
from anse_harness.integrations.github import (
    COMPONENT as GITHUB_COMPONENT,
)
from anse_harness.integrations.github import (
    DRAFT_PR_RISK,
    GitHubAdapter,
    LiveHTTPTransport,
    draft_pr_from_workflow_result,
    github_token_from_env,
)
from anse_harness.integrations.local_double import LocalGitHubDouble
from anse_harness.integrations.mcp_client import (
    PROTOCOL_VERSION,
    MCPToolCapability,
    StdioMCPClient,
    gated_tools_call,
)

__all__ = [
    "AUDIT_OUTCOMES",
    "DRAFT_PR_RISK",
    "GITHUB_COMPONENT",
    "INTEGRATION_ACTIONS",
    "LOCAL_PROTOCOL_OPTIONS",
    "PROTOCOL_JUSTIFICATIONS",
    "PROTOCOL_OPTIONS",
    "PROTOCOL_VERSION",
    "ExternalActionAudit",
    "GitHubAdapter",
    "IntegrationCancelledError",
    "IntegrationError",
    "IntegrationRecorder",
    "IntegrationRequest",
    "IntegrationResponse",
    "LiveHTTPTransport",
    "LocalGitHubDouble",
    "MCPToolCapability",
    "ProtocolDecisionRecord",
    "StdioMCPClient",
    "Transport",
    "audit_artifact_id",
    "draft_pr_from_workflow_result",
    "gated_tools_call",
    "github_token_from_env",
]
