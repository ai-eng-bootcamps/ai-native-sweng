"""Security consolidation layer (Module 10: security and operational readiness).

Module 10 is the course's final consolidation module. It adds no new trace event type and
no new dependency; it composes the safety controls the earlier modules built into one
hardened posture and closes the one gap they left open:

* **Injection defense** (``injection``): the policy-topic clamp that keeps autonomy /
  sandbox / approval / network policy at the platform value no matter what a repository
  file claims - closing the gap Module 4's ``detect_conflicts`` leaves open (it resolves
  conflicts only among the claiming sources).
* **Policy matrix** (``matrix``) + **repository classification** (``capabilities``): the
  consolidated (capability x repository) decision table, evaluated ALONGSIDE the unchanged
  Module 3 ``CommandPolicyEngine``, most-restrictive-wins.
* **Capability shutdown** (``shutdown``): the fail-closed kill-switch.
* **Secret / environment hardening** (``secrets``): the environment allowlist filter and
  packet-level secret scanner, backed by the reused Module 9 trace redaction.
* **Hardened configuration + audit retention** (``config``): the machine-readable startup
  artifact and its validation.

The package REUSES, unchanged: the Module 3 ``CommandPolicyEngine`` and ``ApprovalGate``,
the Module 4 trust levels / precedence / conflict detection, and the Module 9
``TraceEvent.sensitive_keys`` redaction path. It is purely additive over them.
"""

from anse_harness.security.capabilities import (
    REPO_REGISTRY,
    CapabilityClass,
    MatrixDecision,
    RepoClassification,
    classify_repo,
)
from anse_harness.security.config import (
    AuditRetention,
    HardenedConfig,
    default_hardened_config,
)
from anse_harness.security.injection import (
    AUTHORITATIVE_CATEGORIES,
    POLICY_TOPICS,
    PolicyIntent,
    effective_policy_ignores_untrusted,
    resolve_policy_topic,
)
from anse_harness.security.matrix import (
    CMD_TO_CAPABILITY,
    DECISION_RANK,
    DEFAULT_MATRIX,
    OUTCOME_TO_DECISION,
    MatrixResult,
    MatrixRow,
    PolicyMatrix,
)
from anse_harness.security.secrets import (
    DEFAULT_ENV_ALLOWLIST,
    SECRET_PATTERNS,
    filter_env,
    scan_for_secrets,
)
from anse_harness.security.shutdown import CapabilityShutdown

__all__ = [
    "AUTHORITATIVE_CATEGORIES",
    "AuditRetention",
    "CMD_TO_CAPABILITY",
    "CapabilityClass",
    "CapabilityShutdown",
    "DECISION_RANK",
    "DEFAULT_ENV_ALLOWLIST",
    "DEFAULT_MATRIX",
    "HardenedConfig",
    "MatrixDecision",
    "MatrixResult",
    "MatrixRow",
    "OUTCOME_TO_DECISION",
    "POLICY_TOPICS",
    "PolicyIntent",
    "PolicyMatrix",
    "REPO_REGISTRY",
    "RepoClassification",
    "SECRET_PATTERNS",
    "classify_repo",
    "default_hardened_config",
    "effective_policy_ignores_untrusted",
    "filter_env",
    "resolve_policy_topic",
    "scan_for_secrets",
]
