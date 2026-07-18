"""Idempotency keys: the duplicate-execution guard (Lesson 7.4).

Keys derive from task id, workflow id, action type, and artifact version
(arch-ref 53): the same action for the same artifact version always derives the
same key, so a resumed workflow can check the store before repeating an external
action. These fail against the scaffolding stubs and pass once Module 7 is
implemented.
"""

import pytest

from anse_harness.reliability import idempotency_key

pytestmark = pytest.mark.student_impl


def test_same_inputs_always_derive_the_same_key() -> None:
    first = idempotency_key("fx-x", "wf-x", "create_draft_pr", "patch-fx-x-1")
    second = idempotency_key("fx-x", "wf-x", "create_draft_pr", "patch-fx-x-1")
    assert first == second
    assert first.startswith("idem-")
    assert len(first) == len("idem-") + 16


def test_every_field_participates_in_the_key() -> None:
    base = idempotency_key("fx-x", "wf-x", "create_draft_pr", "patch-fx-x-1")
    assert idempotency_key("fx-y", "wf-x", "create_draft_pr", "patch-fx-x-1") != base
    assert idempotency_key("fx-x", "wf-y", "create_draft_pr", "patch-fx-x-1") != base
    assert idempotency_key("fx-x", "wf-x", "post_comment", "patch-fx-x-1") != base
    assert idempotency_key("fx-x", "wf-x", "create_draft_pr", "patch-fx-x-2") != base


def test_a_new_artifact_version_is_a_new_action() -> None:
    # The SAME action against a NEW artifact version must not be deduplicated:
    # re-running validation for attempt 2's patch is legitimate work, not a
    # duplicate of attempt 1's.
    v1 = idempotency_key("fx-x", "wf-x", "trigger_ci", "patch-fx-x-1")
    v2 = idempotency_key("fx-x", "wf-x", "trigger_ci", "patch-fx-x-2")
    assert v1 != v2
