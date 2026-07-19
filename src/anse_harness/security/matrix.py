"""The consolidated policy matrix (Lesson 10.4): capability x repository -> decision.

The matrix is a single total table over (capability class x repository classification)
that says, for every combination, whether the action is allowed, needs approval, or is
denied, and whether it must be audited. It is a CONSOLIDATION, not a replacement: for a
raw command it delegates classification to the unchanged Module 3
``CommandPolicyEngine`` and composes the two decisions MOST-RESTRICTIVE-WINS, so the
matrix can only ever harden the engine's decision, never relax it (deny-by-default
composition).

The default table encodes canonical-reference section 6 defaults, hardened by repository
classification: an untrusted-external repository escalates a class-1 local change to
approval and denies class-2 outright, while class-4 (external consequential) and class-5
(prohibited) are denied everywhere.

SCAFFOLDING: the vocabulary, the default table, and ``PolicyMatrix.lookup`` are supplied;
implement ``PolicyMatrix.evaluate_command`` (the most-restrictive-wins composition) in
Module 10, Lesson 10.4.
"""

from __future__ import annotations

from dataclasses import dataclass

from anse_harness.policy.commands import CommandClass, CommandPolicyEngine, PolicyOutcome
from anse_harness.security.capabilities import (
    CapabilityClass,
    MatrixDecision,
    RepoClassification,
)


@dataclass(frozen=True)
class MatrixRow:
    """One row of the matrix: (capability x repo) -> decision + audit requirement."""

    capability: CapabilityClass
    repo: RepoClassification
    decision: MatrixDecision
    audit_required: bool


@dataclass(frozen=True)
class MatrixResult:
    """The decision for one evaluated action, with the reason recorded in the trace."""

    decision: MatrixDecision
    audit_required: bool
    reason: str


def _default_matrix() -> tuple[MatrixRow, ...]:
    """Canonical section-6 defaults, hardened by repository classification."""
    rows: list[MatrixRow] = []
    for repo in RepoClassification:
        untrusted = repo is RepoClassification.UNTRUSTED_EXTERNAL
        rows += [
            MatrixRow(CapabilityClass.OBSERVATION, repo, MatrixDecision.ALLOW, False),
            MatrixRow(
                CapabilityClass.LOCAL_REVERSIBLE,
                repo,
                MatrixDecision.APPROVE if untrusted else MatrixDecision.ALLOW,
                True,
            ),
            MatrixRow(
                CapabilityClass.LOCAL_CONSEQUENTIAL,
                repo,
                MatrixDecision.DENY if untrusted else MatrixDecision.APPROVE,
                True,
            ),
            MatrixRow(CapabilityClass.EXTERNAL_REVERSIBLE, repo, MatrixDecision.APPROVE, True),
            MatrixRow(CapabilityClass.EXTERNAL_CONSEQUENTIAL, repo, MatrixDecision.DENY, True),
            MatrixRow(CapabilityClass.PROHIBITED, repo, MatrixDecision.DENY, True),
        ]
    return tuple(rows)


#: The default consolidated matrix (total over the 6 x 2 grid).
DEFAULT_MATRIX: tuple[MatrixRow, ...] = _default_matrix()

#: Map the six Module 3 command classes onto the canonical capability classes.
CMD_TO_CAPABILITY: dict[CommandClass, CapabilityClass] = {
    CommandClass.READ_ONLY: CapabilityClass.OBSERVATION,
    CommandClass.VALIDATION: CapabilityClass.OBSERVATION,
    CommandClass.MUTATING: CapabilityClass.LOCAL_REVERSIBLE,
    CommandClass.DESTRUCTIVE: CapabilityClass.LOCAL_CONSEQUENTIAL,
    CommandClass.NETWORKED: CapabilityClass.EXTERNAL_REVERSIBLE,
    CommandClass.PROHIBITED: CapabilityClass.PROHIBITED,
}

#: Map the four command-policy outcomes onto the matrix's three decisions.
OUTCOME_TO_DECISION: dict[PolicyOutcome, MatrixDecision] = {
    PolicyOutcome.ALLOW: MatrixDecision.ALLOW,
    PolicyOutcome.ALLOW_WITH_VALIDATION: MatrixDecision.ALLOW,
    PolicyOutcome.REQUIRE_APPROVAL: MatrixDecision.APPROVE,
    PolicyOutcome.DENY: MatrixDecision.DENY,
}

#: Restrictiveness rank for most-restrictive-wins composition.
DECISION_RANK: dict[MatrixDecision, int] = {
    MatrixDecision.ALLOW: 0,
    MatrixDecision.APPROVE: 1,
    MatrixDecision.DENY: 2,
}


class PolicyMatrix:
    """The consolidated matrix, evaluated ALONGSIDE the Module 3 command engine.

    Not a fork of the engine: ``evaluate_command`` delegates classification to the real
    ``CommandPolicyEngine``, maps the command class onto a capability class, then composes
    the engine's decision with the matrix row most-restrictive-wins.
    """

    def __init__(
        self,
        rows: tuple[MatrixRow, ...] = DEFAULT_MATRIX,
        engine: CommandPolicyEngine | None = None,
    ) -> None:
        self._by_key = {(row.capability, row.repo): row for row in rows}
        self._engine = engine or CommandPolicyEngine()

    def lookup(self, capability: CapabilityClass, repo: RepoClassification) -> MatrixResult:
        """Return the matrix decision for one (capability x repo) cell."""
        row = self._by_key[(capability, repo)]
        return MatrixResult(row.decision, row.audit_required, f"matrix[{capability},{repo}]")

    def evaluate_command(self, command: list[str], repo: RepoClassification) -> MatrixResult:
        """Decide one argv command against ``repo``, most-restrictive-wins.

        Delegate the classification to the unchanged Module 3 ``CommandPolicyEngine``
        (``self._engine.evaluate``), translate the engine's outcome to a
        ``MatrixDecision`` via ``OUTCOME_TO_DECISION`` and its command class to a
        capability class via ``CMD_TO_CAPABILITY`` (an unclassified command has no class:
        treat it as ``PROHIBITED``), then look up ``(capability, repo)`` in the matrix and
        return whichever of the two decisions is MORE restrictive (higher
        ``DECISION_RANK``). The matrix may harden the engine's decision but must never
        relax it. Carry ``audit_required`` from the matrix row and set ``reason`` to the
        engine's ``render()`` when the engine's decision stands, or a "matrix hardened"
        note when the matrix tightens it.

        Lesson 10.4: the consolidated approval matrix. Implement in Module 10.
        """
        raise NotImplementedError(
            "Module 10, Lesson 10.4: compose the Module 3 CommandPolicyEngine decision "
            "with the (capability x repo) matrix row, most-restrictive-wins. Delegate "
            "classification to self._engine.evaluate; the matrix may only harden."
        )
