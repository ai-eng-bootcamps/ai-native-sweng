"""Hardened deployment configuration + audit retention (Lessons 10.4-10.6).

The hardened configuration is the single machine-readable artifact a deployment consumes
at startup to pin its security posture: the repository classification, the policy matrix,
the network policy (default deny), the credential scopes, the environment allowlist, the
capability kill-switch, and the audit-retention rule. It is the Module 10 lab deliverable
("produce a hardened deployment configuration") and the artifact the ``mf-001`` grader
checks - a harness configuration, not container orchestration.

``HardenedConfig`` round-trips to and from that JSON; ``validate`` checks the hardening
invariants (network denies by default, the consequential classes are denied, the
adversarial repository is classified untrusted); ``AuditRetention`` says which event
types survive and for how long (Lesson 10.6 trace retention).

SCAFFOLDING: the dataclasses, ``default_hardened_config``, and the JSON round-trip are
supplied; implement ``AuditRetention.retains`` and ``HardenedConfig.validate`` in
Module 10, Lessons 10.4-10.6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anse_harness.security.capabilities import (
    CapabilityClass,
    MatrixDecision,
    RepoClassification,
)
from anse_harness.security.matrix import DEFAULT_MATRIX, MatrixRow
from anse_harness.security.secrets import DEFAULT_ENV_ALLOWLIST

#: Capability classes denied everywhere in a hardened posture (canonical section 6:
#: external-consequential and prohibited are human-only / deny-and-record).
_CONSEQUENTIAL_CLASSES: frozenset[CapabilityClass] = frozenset(
    {CapabilityClass.EXTERNAL_CONSEQUENTIAL, CapabilityClass.PROHIBITED}
)


@dataclass(frozen=True)
class AuditRetention:
    """Which trace event types are retained, and for how long (Lesson 10.6)."""

    max_age_days: int
    retained_event_types: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_age_days": self.max_age_days,
            "retained_event_types": list(self.retained_event_types),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditRetention:
        return cls(
            max_age_days=int(data["max_age_days"]),
            retained_event_types=tuple(data["retained_event_types"]),
        )

    def retains(self, event_type: str) -> bool:
        """Report whether an event of ``event_type`` is kept by the retention rule.

        Return True iff ``event_type`` is in ``self.retained_event_types``. The
        security-relevant events (policy decisions, approvals, escalations) are retained
        so an incident can be reconstructed; everything else may be pruned.

        Lesson 10.6: audit events are retained. Implement in Module 10.
        """
        raise NotImplementedError(
            "Module 10, Lesson 10.6: return whether event_type is in self.retained_event_types."
        )


@dataclass(frozen=True)
class HardenedConfig:
    """The hardened deployment configuration (Lesson 10.4-10.6 lab deliverable)."""

    repository_classification: dict[str, RepoClassification]
    policy_matrix: tuple[MatrixRow, ...]
    network_default: str
    network_allow_destinations: tuple[str, ...]
    credential_scopes: dict[str, tuple[str, ...]]
    env_allowlist: tuple[str, ...]
    disabled_capabilities: tuple[str, ...]
    audit_retention: AuditRetention

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the machine-readable startup JSON object."""
        return {
            "audit_retention": self.audit_retention.to_dict(),
            "capability_shutdown": {"disabled": list(self.disabled_capabilities)},
            "credential_scopes": {k: list(v) for k, v in self.credential_scopes.items()},
            "env_allowlist": list(self.env_allowlist),
            "network_policy": {
                "default": self.network_default,
                "allow_destinations": list(self.network_allow_destinations),
            },
            "policy_matrix": [
                {
                    "capability": row.capability.value,
                    "repo": row.repo.value,
                    "decision": row.decision.value,
                    "audit_required": row.audit_required,
                }
                for row in self.policy_matrix
            ],
            "repository_classification": {
                k: v.value for k, v in self.repository_classification.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HardenedConfig:
        """Parse the startup JSON object. Missing a required section is an error."""
        required = {
            "repository_classification",
            "policy_matrix",
            "network_policy",
            "credential_scopes",
            "env_allowlist",
            "capability_shutdown",
            "audit_retention",
        }
        missing = required - data.keys()
        if missing:
            raise ValueError(f"hardened config is missing sections: {sorted(missing)}")
        return cls(
            repository_classification={
                k: RepoClassification(v) for k, v in data["repository_classification"].items()
            },
            policy_matrix=tuple(
                MatrixRow(
                    CapabilityClass(row["capability"]),
                    RepoClassification(row["repo"]),
                    MatrixDecision(row["decision"]),
                    bool(row["audit_required"]),
                )
                for row in data["policy_matrix"]
            ),
            network_default=str(data["network_policy"]["default"]),
            network_allow_destinations=tuple(data["network_policy"].get("allow_destinations", ())),
            credential_scopes={k: tuple(v) for k, v in data["credential_scopes"].items()},
            env_allowlist=tuple(data["env_allowlist"]),
            disabled_capabilities=tuple(data["capability_shutdown"].get("disabled", ())),
            audit_retention=AuditRetention.from_dict(data["audit_retention"]),
        )

    @classmethod
    def load(cls, path: Path) -> HardenedConfig:
        """Read and parse the hardened-config JSON file at ``path``."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def validate(self) -> list[str]:
        """Return the hardening-invariant violations; an empty list means the config holds.

        Check, and report a short problem string for each that fails:

        * the network policy defaults to "deny" (``self.network_default == "deny"``);
        * every policy-matrix row for an external-consequential or prohibited capability
          (``_CONSEQUENTIAL_CLASSES``) decides ``MatrixDecision.DENY``;
        * the adversarial ``ai-native-sweng-minefield`` is classified
          ``RepoClassification.UNTRUSTED_EXTERNAL``;
        * the policy matrix is total - it covers every (capability class x repository
          classification) cell.

        A hardened config that violates any of these is unsafe to deploy. Return the list
        of violations (empty = valid), so a caller can report exactly what is wrong.

        Lessons 10.4-10.6: the gradeable hardened-configuration check. Implement in
        Module 10.
        """
        raise NotImplementedError(
            "Module 10, Lessons 10.4-10.6: return the list of hardening-invariant "
            "violations (network default deny, consequential classes denied, minefield "
            "untrusted, matrix total); an empty list means the config is valid."
        )


def default_hardened_config() -> HardenedConfig:
    """Build the reference hardened configuration (the committed exemplar deliverable).

    The offline hardened posture: the default matrix, network denied by default, the
    external capability classes (network / external-consequential) disabled by the
    kill-switch while local development stays governed by the matrix, least-scope GitHub
    credentials, the default environment allowlist, and retention of the security-relevant
    trace events for ninety days.
    """
    from anse_harness.security.capabilities import REPO_REGISTRY

    return HardenedConfig(
        repository_classification=dict(REPO_REGISTRY),
        policy_matrix=DEFAULT_MATRIX,
        network_default="deny",
        network_allow_destinations=(),
        credential_scopes={"github": ("repo:status", "pull_request:write")},
        env_allowlist=tuple(sorted(DEFAULT_ENV_ALLOWLIST)),
        disabled_capabilities=(
            CapabilityClass.EXTERNAL_REVERSIBLE.value,
            CapabilityClass.EXTERNAL_CONSEQUENTIAL.value,
        ),
        audit_retention=AuditRetention(
            max_age_days=90,
            retained_event_types=("policy_evaluated", "approval_resolved", "escalation_created"),
        ),
    )
