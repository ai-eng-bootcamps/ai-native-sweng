"""Hardened config validation + audit retention (Lessons 10.4-10.6).

``HardenedConfig.validate`` returns the hardening-invariant violations (empty = valid);
the committed configuration must pass, and each tampered variant must be caught.
``AuditRetention.retains`` decides which trace events survive.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from anse_harness.security import (
    AuditRetention,
    HardenedConfig,
    MatrixDecision,
    RepoClassification,
    default_hardened_config,
)
from anse_harness.security.capabilities import CapabilityClass

pytestmark = pytest.mark.student_impl

CONFIG = Path(__file__).resolve().parents[2] / "configs" / "policies" / "hardened-config.json"


def test_committed_hardened_config_validates() -> None:
    assert HardenedConfig.load(CONFIG).validate() == []
    assert default_hardened_config().validate() == []


def test_validate_flags_a_permissive_network_default() -> None:
    config = dataclasses.replace(default_hardened_config(), network_default="allow")
    problems = config.validate()
    assert any("network" in problem for problem in problems)


def test_validate_flags_an_allowed_consequential_class() -> None:
    base = default_hardened_config()
    tampered_rows = tuple(
        dataclasses.replace(row, decision=MatrixDecision.ALLOW)
        if row.capability is CapabilityClass.EXTERNAL_CONSEQUENTIAL
        else row
        for row in base.policy_matrix
    )
    config = dataclasses.replace(base, policy_matrix=tampered_rows)
    assert config.validate() != []


def test_validate_flags_a_trusted_minefield() -> None:
    base = default_hardened_config()
    classification = dict(base.repository_classification)
    classification["ai-native-sweng-minefield"] = RepoClassification.TRUSTED_INTERNAL
    config = dataclasses.replace(base, repository_classification=classification)
    assert any("minefield" in problem for problem in config.validate())


def test_validate_flags_a_non_total_matrix() -> None:
    base = default_hardened_config()
    # Drop one cell so the matrix is no longer total.
    config = dataclasses.replace(base, policy_matrix=base.policy_matrix[:-1])
    assert any("total" in problem for problem in config.validate())


def test_audit_retention_retains_the_security_events() -> None:
    retention = AuditRetention(
        max_age_days=90,
        retained_event_types=("policy_evaluated", "approval_resolved", "escalation_created"),
    )
    assert retention.retains("policy_evaluated")
    assert retention.retains("escalation_created")
    assert not retention.retains("model_requested")


def test_committed_config_retains_the_blocked_action_evidence() -> None:
    # The events that reconstruct a blocked action must be retained.
    retention = HardenedConfig.load(CONFIG).audit_retention
    assert retention.retains("policy_evaluated")
    assert retention.retains("escalation_created")
