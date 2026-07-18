"""Worker contract and invocation-record schemas (canonical-reference.md section 9).

The contract dataclasses and the standard Module 6 contracts are SUPPLIED
infrastructure, so these tests run in the default suite: they pin the payload round
trips, the capability sets to the exact Module 5 registry tool lists (a contract that
drifts from the registry a worker actually receives is worse than no contract), and
the exclusion lists that carry reviewer independence (arch-ref 43).
"""

from anse_harness.workers.contract import (
    READ_ONLY_CAPABILITIES,
    WRITE_CAPABILITIES,
    ContextRequirements,
    WorkerContract,
    WorkerInvocationRecord,
    fix_worker_contract,
    implementer_contract,
    reviewer_contract,
)


def test_worker_contract_payload_round_trip() -> None:
    contract = implementer_contract(cost_budget_usd=0.25, iteration_limit=5)
    payload = contract.to_payload()
    assert payload["artifact_type"] == "worker_contract"
    assert payload["limits"] == {
        "time_budget_seconds": 600,
        "cost_budget_usd": 0.25,
        "iteration_limit": 5,
    }
    assert WorkerContract.from_payload(payload) == contract


def test_standard_contract_capabilities_match_the_module5_registries() -> None:
    assert implementer_contract().allowed_capabilities == WRITE_CAPABILITIES
    assert fix_worker_contract().allowed_capabilities == WRITE_CAPABILITIES
    reviewer = reviewer_contract("correctness")
    assert reviewer.worker_type == "correctness_reviewer"
    assert reviewer.allowed_capabilities == READ_ONLY_CAPABILITIES
    # Everything write-capable is explicitly prohibited for a reviewer.
    for name in WRITE_CAPABILITIES:
        if name not in READ_ONLY_CAPABILITIES:
            assert name in reviewer.prohibited_capabilities


def test_reviewer_and_fixer_context_exclusions_carry_independence() -> None:
    reviewer = reviewer_contract("tests")
    assert "implementer_reasoning_history" in reviewer.context.excluded
    assert "previous_reviewer_conclusions" in reviewer.context.excluded
    fixer = fix_worker_contract()
    assert "review_conversation" in fixer.context.excluded
    assert "accepted_findings_with_evidence" in fixer.context.required


def test_invocation_record_round_trip() -> None:
    record = WorkerInvocationRecord(
        worker_invocation_id="wf-1-worker-a-implement-1",
        worker_type="implementer",
        assigned_task="t-1/worker-a",
        model_configuration="scripted",
        context_packet_id="cp-t-1/worker-a-implementer",
        available_capabilities=WRITE_CAPABILITIES,
        status="completed",
        result="patch-t-1-worker-a-1",
        cost=0.0123,
        duration_seconds=1.5,
        parent_workflow="wf-1",
        parent_worker=None,
    )
    payload = record.to_payload()
    assert payload["artifact_type"] == "worker_invocation_record"
    assert WorkerInvocationRecord.from_payload(payload) == record


def test_context_requirements_round_trip() -> None:
    context = ContextRequirements(required=("a", "b"), excluded=("c",))
    assert ContextRequirements.from_payload(context.to_payload()) == context
