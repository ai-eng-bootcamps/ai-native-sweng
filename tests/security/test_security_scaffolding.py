"""Supplied Module 10 security scaffolding + committed-artifact hygiene (default suite).

These exercise only the SUPPLIED pieces of the security package - the vocabulary, the
default matrix table and its ``lookup``, the config round-trip, the detector table, the
shutdown container's ``disable``/``enabled`` - plus structural checks over the two
committed Module 10 artifacts. They must pass on a fresh clone (stubs included), so they
never call a student-implemented function (``evaluate_command``, ``guard``,
``scan_for_secrets``, ``filter_env``, ``resolve_policy_topic``,
``effective_policy_ignores_untrusted``, ``retains``, ``validate``).
"""

from __future__ import annotations

import ast
from pathlib import Path

from anse_harness.security import (
    DEFAULT_ENV_ALLOWLIST,
    DEFAULT_MATRIX,
    POLICY_TOPICS,
    REPO_REGISTRY,
    SECRET_PATTERNS,
    AuditRetention,
    CapabilityClass,
    CapabilityShutdown,
    HardenedConfig,
    MatrixDecision,
    MatrixRow,
    PolicyMatrix,
    RepoClassification,
    classify_repo,
    default_hardened_config,
)
from anse_harness.security import capabilities as capabilities_module
from anse_harness.security import config as config_module
from anse_harness.security import injection as injection_module
from anse_harness.security import matrix as matrix_module
from anse_harness.security import secrets as secrets_module
from anse_harness.security import shutdown as shutdown_module
from anse_harness.tracing import read_trace
from anse_harness.tracing.events import EVENT_TYPES

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "traces" / "m10" / "adversarial_demo.jsonl"
CONFIG = ROOT / "configs" / "policies" / "hardened-config.json"


# --- vocabulary + registry -------------------------------------------------


def test_capability_classes_are_the_canonical_six() -> None:
    assert [c.value for c in CapabilityClass] == [
        "class-0-observation",
        "class-1-local-reversible",
        "class-2-local-consequential",
        "class-3-external-reversible",
        "class-4-external-consequential",
        "class-5-prohibited",
    ]


def test_repo_registry_classifies_the_three_targets() -> None:
    assert REPO_REGISTRY["ai-native-sweng-bookit"] is RepoClassification.TRUSTED_INTERNAL
    assert REPO_REGISTRY["ai-native-sweng-bookit-platform"] is RepoClassification.TRUSTED_INTERNAL
    assert REPO_REGISTRY["ai-native-sweng-minefield"] is RepoClassification.UNTRUSTED_EXTERNAL


def test_classify_repo_defaults_unknown_to_untrusted() -> None:
    assert classify_repo("some-random-repo") is RepoClassification.UNTRUSTED_EXTERNAL
    assert classify_repo("ai-native-sweng-bookit") is RepoClassification.TRUSTED_INTERNAL


# --- the default matrix (supplied table + lookup) --------------------------


def test_default_matrix_is_total_over_the_grid() -> None:
    covered = {(row.capability, row.repo) for row in DEFAULT_MATRIX}
    expected = {(cap, repo) for cap in CapabilityClass for repo in RepoClassification}
    assert covered == expected


def test_matrix_lookup_is_monotone_and_denies_consequential_classes() -> None:
    matrix = PolicyMatrix()
    rank = {MatrixDecision.ALLOW: 0, MatrixDecision.APPROVE: 1, MatrixDecision.DENY: 2}
    for cap in CapabilityClass:
        trusted = matrix.lookup(cap, RepoClassification.TRUSTED_INTERNAL).decision
        untrusted = matrix.lookup(cap, RepoClassification.UNTRUSTED_EXTERNAL).decision
        # untrusted-external is never more permissive than trusted-internal
        assert rank[untrusted] >= rank[trusted]
    for cap in (CapabilityClass.EXTERNAL_CONSEQUENTIAL, CapabilityClass.PROHIBITED):
        for repo in RepoClassification:
            assert matrix.lookup(cap, repo).decision is MatrixDecision.DENY


# --- shutdown container (supplied disable/enabled) -------------------------


def test_shutdown_disable_and_enabled_are_supplied() -> None:
    switch = CapabilityShutdown()
    assert switch.enabled("class-1-local-reversible")
    switch.disable("class-1-local-reversible")
    switch.disable("class-1-local-reversible")  # idempotent
    assert not switch.enabled("class-1-local-reversible")
    assert switch.disabled == {"class-1-local-reversible"}


# --- secret detector table + env allowlist (supplied data) -----------------


def test_secret_patterns_and_allowlist_are_supplied() -> None:
    kinds = [kind for kind, _ in SECRET_PATTERNS]
    assert kinds == ["aws_access_key", "github_pat", "aws_secret_key"]
    assert "PATH" in DEFAULT_ENV_ALLOWLIST
    assert "AWS_SECRET_ACCESS_KEY" not in DEFAULT_ENV_ALLOWLIST


# --- injection topic set (supplied data) -----------------------------------


def test_policy_topics_cover_the_clamped_axes() -> None:
    assert frozenset({"autonomy", "sandbox", "approval", "network"}) == POLICY_TOPICS


# --- hardened config round-trip (supplied to_dict/from_dict/load) ----------


def test_default_hardened_config_round_trips() -> None:
    config = default_hardened_config()
    reparsed = HardenedConfig.from_dict(config.to_dict())
    assert reparsed == config
    # The config's policy_matrix reuses the matrix MatrixRow type (DRY, not a parallel).
    assert all(isinstance(row, MatrixRow) for row in config.policy_matrix)


def test_audit_retention_round_trips() -> None:
    retention = AuditRetention(max_age_days=90, retained_event_types=("policy_evaluated",))
    assert AuditRetention.from_dict(retention.to_dict()) == retention


def test_from_dict_rejects_a_config_missing_a_section() -> None:
    data = default_hardened_config().to_dict()
    del data["network_policy"]
    try:
        HardenedConfig.from_dict(data)
    except ValueError as exc:
        assert "network_policy" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("from_dict accepted a config missing a required section")


# --- committed artifacts: the hardened config ------------------------------


def test_committed_hardened_config_matches_the_reference_defaults() -> None:
    import json

    committed = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert committed == default_hardened_config().to_dict()


def test_committed_hardened_config_is_a_hardened_posture() -> None:
    config = HardenedConfig.load(CONFIG)  # supplied load + from_dict, not validate
    assert config.network_default == "deny"
    assert config.repository_classification["ai-native-sweng-minefield"] is (
        RepoClassification.UNTRUSTED_EXTERNAL
    )
    for row in config.policy_matrix:
        if row.capability in (
            CapabilityClass.EXTERNAL_CONSEQUENTIAL,
            CapabilityClass.PROHIBITED,
        ):
            assert row.decision is MatrixDecision.DENY


# --- committed artifacts: the adversarial demo trace -----------------------


def test_committed_demo_trace_uses_frozen_vocabulary_and_leaks_no_credential() -> None:
    text = TRACE.read_text(encoding="utf-8")
    # No fixture credential shape reaches the committed trace.
    assert "AKIA" not in text
    assert "ghp_" not in text
    assert "wJalrXUtnFEMI" not in text
    for event in read_trace(TRACE):
        assert event.event_type in EVENT_TYPES
        # Module 10 adds no trace event type: no security_* vocabulary.
        assert not event.event_type.startswith("security_")


def test_committed_demo_trace_tells_the_blocked_action_story() -> None:
    events = read_trace(TRACE)
    assert [event.event_type for event in events] == [
        "policy_evaluated",
        "policy_evaluated",
        "tool_requested",
        "escalation_created",
    ]
    # classify -> clamp, block, redact -> escalate (fail closed).
    assert events[0].payload["effective_value"] == "3"  # autonomy held at platform value
    assert events[1].payload["decision"] == "deny"  # git push denied despite AGENTS.md
    assert events[2].payload["attempted_exfiltration"]["github_token"] == "[REDACTED]"
    assert events[-1].event_type == "escalation_created"


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


def test_security_code_imports_only_stdlib_and_anse_harness() -> None:
    stdlib = {"__future__", "json", "re", "dataclasses", "typing", "pathlib", "enum"}
    modules = [
        Path(capabilities_module.__file__),
        Path(matrix_module.__file__),
        Path(shutdown_module.__file__),
        Path(injection_module.__file__),
        Path(secrets_module.__file__),
        Path(config_module.__file__),
    ]
    third_party: set[str] = set()
    for module_path in modules:
        for name in _top_level_imports(module_path):
            if name == "anse_harness" or name in stdlib:
                continue
            third_party.add(name)
    assert third_party == set(), f"security code imported non-stdlib modules: {third_party}"
