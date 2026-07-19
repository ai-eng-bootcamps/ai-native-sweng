"""Deterministic in-process GitHub double: the offline integration transport (Lesson 9.2).

This is the ScriptedAdapter pattern lifted to the integration boundary. It
implements the ``Transport`` protocol with fixed fixture data and no network, so
every committed test and the committed ``traces/m09`` run execute at zero cost
and open no socket. It is the honest counterpart to the live ``urllib``
transport: identical adapter logic runs against both; only this class stands in
for the network.

One thing the module content must say plainly: **a green integration test that
names no repository is running against this double, not against GitHub.** The
course's replay machinery compares model requests; it does not touch tools,
sockets, or credentials. Integration determinism comes from this double, not from
replay.

The double enforces two safety properties at the boundary, so the adapter is
never *trusted* to have enforced them: it refuses to create anything that is not
a draft, and it deduplicates create requests by idempotency key so a repeated
create returns the same pull request instead of a second one.

SCAFFOLDING: supplied. Students consume the double as their offline transport.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anse_harness.integrations.contracts import (
    IntegrationError,
    IntegrationRequest,
    IntegrationResponse,
)


class LocalGitHubDouble:
    """An in-process, deterministic stand-in for the GitHub REST API.

    Serves fixture issues and CI status; records created draft pull requests by
    idempotency key so a repeated create is deduplicated. Set ``raise_timeout`` to
    make the next ``send`` raise a retryable timeout - the deterministic,
    offline way to exercise the timeout path (Lesson 9.1 lifecycle).
    """

    def __init__(self, issues: dict[int, dict[str, Any]], ci: dict[str, dict[str, Any]]) -> None:
        self._issues = issues
        self._ci = ci
        self._prs_by_key: dict[str, dict[str, Any]] = {}
        self._next_pr = 101
        #: Every request that reached the transport, in order (for assertions).
        self.sent: list[IntegrationRequest] = []
        #: Test lever: when True the next ``send`` raises a retryable timeout.
        self.raise_timeout = False

    @classmethod
    def from_fixtures(cls, directory: Path) -> LocalGitHubDouble:
        """Load ``issues.json`` (a list of issue objects) and ``ci.json`` (a
        ref->status map) from ``directory`` - the same content a live intake reads
        from the seeded backlog, served offline."""
        issues_raw = json.loads((directory / "issues.json").read_text(encoding="utf-8"))
        ci_raw = json.loads((directory / "ci.json").read_text(encoding="utf-8"))
        issues = {int(item["number"]): dict(item) for item in issues_raw}
        ci = {str(ref): dict(status) for ref, status in ci_raw.items()}
        return cls(issues, ci)

    @property
    def created_prs(self) -> dict[str, dict[str, Any]]:
        """The draft pull requests the double has recorded, keyed by idem key."""
        return dict(self._prs_by_key)

    def send(self, request: IntegrationRequest) -> IntegrationResponse:
        self.sent.append(request)
        if self.raise_timeout:
            raise IntegrationError("read timed out", retryable=True)
        if request.action == "read_issue":
            return self._read_issue(request)
        if request.action == "read_ci_status":
            return self._read_ci_status(request)
        if request.action == "create_draft_pr":
            return self._create_draft_pr(request)
        raise IntegrationError(f"unknown action {request.action}", retryable=False)

    def _read_issue(self, request: IntegrationRequest) -> IntegrationResponse:
        number = int(request.body["number"])
        if number not in self._issues:
            raise IntegrationError(f"issue {number} not found", retryable=False)
        return IntegrationResponse("read_issue", 200, dict(self._issues[number]))

    def _read_ci_status(self, request: IntegrationRequest) -> IntegrationResponse:
        ref = str(request.body["ref"])
        status = self._ci.get(ref, {"state": "unknown", "total_count": 0})
        return IntegrationResponse("read_ci_status", 200, dict(status))

    def _create_draft_pr(self, request: IntegrationRequest) -> IntegrationResponse:
        key = request.idempotency_key or ""
        if key in self._prs_by_key:
            pr = self._prs_by_key[key]
            return IntegrationResponse("create_draft_pr", 200, {**pr, "deduped": True})
        # The boundary refuses any non-draft create: the safety property does not
        # depend on the adapter having shaped the request correctly.
        if request.body.get("draft") is not True:
            raise IntegrationError(
                "refused: only draft pull requests are permitted at this boundary",
                retryable=False,
            )
        pr = {
            "number": self._next_pr,
            "draft": True,
            "state": "open",
            "html_url": f"https://github.invalid/pull/{self._next_pr}",
            "title": request.body.get("title", ""),
        }
        self._next_pr += 1
        self._prs_by_key[key] = pr
        return IntegrationResponse("create_draft_pr", 201, {**pr, "deduped": False})
