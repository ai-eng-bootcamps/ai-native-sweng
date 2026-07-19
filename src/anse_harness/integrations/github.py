"""GitHub repository-platform adapter: logic, request shaping, approval gating (Lessons 9.2, 9.3).

The adapter is the same code offline and live; only the injected ``Transport``
differs. Its surface is exactly ``read_issue`` / ``read_ci_status`` /
``create_draft_pr`` (arch-ref 60): reading issue metadata and CI status is
allowed without approval; creating a draft pull request is an external reversible
action (canonical §6 class 3) that routes through the Module 3 ``ApprovalGate``
and is idempotent by a Module 7 derived key. There is no ``merge``, ``push``,
``create_release``, or ``deploy`` method - the prohibited class-4 actions are
absent from the surface, so they cannot be requested.

Credential handling (arch-ref 58): the token is read from the environment, held
by the adapter, and placed only in the ``Authorization`` header the transport
builds. It is never written to a request body, an audit record, or a trace
payload.

SCAFFOLDING: ``github_token_from_env``, ``LiveHTTPTransport``, the adapter
constructor and ``_headers``, and ``draft_pr_from_workflow_result`` are supplied.
Implement ``read_issue``, ``read_ci_status``, and ``create_draft_pr`` in Module 9,
Lessons 9.2-9.3.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from anse_harness.approvals.gate import ApprovalGate
from anse_harness.integrations.contracts import (
    IntegrationRecorder,
    IntegrationRequest,
    IntegrationResponse,
    Transport,
)
from anse_harness.tracing import TraceWriter

#: The component name every GitHub-adapter trace event carries.
COMPONENT = "integration.github"

#: The risk label a draft-PR approval request carries (canonical §6 class 3).
DRAFT_PR_RISK = "external-reversible (class 3)"


def github_token_from_env(variable: str = "GITHUB_TOKEN") -> str:
    """Read a scoped GitHub token from the environment (arch-ref 58).

    Credentials come from the environment, never from model context or a task
    payload. Raises if the variable is unset - the boundary fails closed rather
    than sending an unauthenticated request.
    """
    token = os.environ.get(variable)
    if not token:
        raise RuntimeError(
            f"integration credential {variable!r} is not set; export a scoped token "
            "before running a live integration (offline runs use the local double)"
        )
    return token


class LiveHTTPTransport:
    """The one network-touching transport: GitHub REST over stdlib ``urllib``.

    NEVER executed in the test suite or in an offline run - the local double
    stands in for it there. It exists so the identical adapter logic can reach a
    real repository when a credential and a test repository are supplied. HTTP
    errors map onto the Module 7 taxonomy: 5xx and 429 are retryable, other 4xx
    are not; a timeout or a transport error is retryable.
    """

    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def send(self, request: IntegrationRequest) -> IntegrationResponse:
        from anse_harness.integrations.contracts import IntegrationError

        url = f"{self._base_url}{request.path}"
        data = json.dumps(request.body).encode("utf-8") if request.method == "POST" else None
        http_request = urllib.request.Request(
            url, data=data, method=request.method, headers=self._headers()
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                return IntegrationResponse(request.action, response.status, parsed)
        except urllib.error.HTTPError as error:
            retryable = error.code >= 500 or error.code == 429
            raise IntegrationError(
                f"{request.action} failed: HTTP {error.code}", retryable=retryable
            ) from error
        except (TimeoutError, urllib.error.URLError) as error:
            raise IntegrationError(f"{request.action} failed: {error}", retryable=True) from error


class GitHubAdapter:
    """Shapes, gates, traces, and sends external actions over an injected transport."""

    def __init__(
        self,
        transport: Transport,
        token: str,
        gate: ApprovalGate,
        *,
        run_id: str,
        workflow_id: str,
        tracer: TraceWriter | None = None,
    ) -> None:
        self._transport = transport
        #: From the environment; only ever placed on the wire, never in a payload.
        self._token = token
        self._gate = gate
        self._rec = IntegrationRecorder(tracer, run_id, workflow_id, "evt-int")

    def _headers(self) -> dict[str, str]:
        """The wire headers, including the credential. Shaped, never traced."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
        }

    def read_issue(self, number: int) -> dict[str, Any]:
        """Read one issue's metadata for intake (Lesson 9.3). Reading is allowed
        without approval (arch-ref 60)."""
        raise NotImplementedError(
            "Module 9, Lesson 9.3: shape a read_issue IntegrationRequest "
            "(GET /issues/<number>, body {'number': number}), emit a tool_requested "
            "event via self._rec, send it through self._transport, emit tool_completed "
            "(payload {'action', 'issue'}), and return the response data."
        )

    def read_ci_status(self, ref: str) -> dict[str, Any]:
        """Read the combined CI status for a ref (Lesson 9.3). Allowed without
        approval (arch-ref 60)."""
        raise NotImplementedError(
            "Module 9, Lesson 9.3: shape a read_ci_status IntegrationRequest "
            "(GET /commits/<ref>/status, body {'ref': ref}), emit tool_requested, "
            "send it, emit tool_completed (payload {'action', 'state'}), and return "
            "the response data."
        )

    def create_draft_pr(
        self,
        *,
        task_id: str,
        workflow_id: str,
        artifact_version: str,
        title: str,
        head: str,
        base: str,
        diff: str,
        cancel: bool = False,
    ) -> dict[str, Any]:
        """Prepare a DRAFT pull request for an approved patch (Lesson 9.2).

        A consequential external action: it routes through the approval gate, is
        idempotent by a derived key, is cancellable before the send, and records
        an audit artifact whatever the outcome. ``draft`` is hard-coded True.
        """
        raise NotImplementedError(
            "Module 9, Lesson 9.2:\n"
            "  1. key = idempotency_key(task_id, workflow_id, 'create_draft_pr', "
            "artifact_version) (Module 7).\n"
            "  2. Shape the body with draft=True HARD-CODED and the marker "
            "'<!-- idem:<key> -->' appended to the PR body; build a create_draft_pr "
            "IntegrationRequest (POST /pulls, idempotency_key=key).\n"
            "  3. Route through self._gate.request(ApprovalRequest(action='create_draft_pr', "
            "risk=DRAFT_PR_RISK, diff=diff, validation_ok=True, ...)); emit "
            "approval_requested then approval_resolved. If not APPROVED, emit a rejected "
            "ExternalActionAudit (artifact_created) and raise IntegrationError(retryable=False).\n"
            "  4. If cancel, emit tool_failed(status='cancelled') and a cancelled audit, "
            "then raise IntegrationCancelledError - the request must not reach the transport.\n"
            "  5. Otherwise emit tool_requested, send through self._transport, emit "
            "tool_completed, build a completed/deduplicated ExternalActionAudit "
            "(artifact_created), and return the response data. The token is never placed "
            "in any payload."
        )


def draft_pr_from_workflow_result(
    result: Any,
    *,
    platform: GitHubAdapter | None,
    task_id: str,
    workflow_id: str,
    artifact_version: str,
    title: str,
    head: str,
    base: str,
) -> dict[str, Any] | None:
    """Gated PrepareResult hook: package an approved patch into a draft PR.

    This is the ``platform=None`` seam applied outside the workflow engine, so no
    frozen engine code changes and the Module 5-8 workflows are byte-identical.
    When ``platform`` is None (the default for every Module 5-8 workflow), this is
    a no-op returning None. When a ``GitHubAdapter`` is supplied, it packages the
    result's patch into a draft pull request request through the adapter (approval,
    idempotency, and audit all handled there).
    """
    if platform is None:
        return None
    patch = getattr(result, "patch", None)
    if not patch:
        raise ValueError("cannot prepare a draft PR: the workflow produced no patch")
    return platform.create_draft_pr(
        task_id=task_id,
        workflow_id=workflow_id,
        artifact_version=artifact_version,
        title=title,
        head=head,
        base=base,
        diff=patch,
    )
