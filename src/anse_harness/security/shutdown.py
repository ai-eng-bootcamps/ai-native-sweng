"""Capability shutdown / kill-switch (Lesson 10.6: disabling capabilities).

Operational readiness requires a way to turn a capability off without redeploying: a
set of disabled capability ids that forces every affected decision to a loud DENY,
whatever the policy matrix or command engine would otherwise have said. It is checked at
tool-registry and adapter construction, so a disabled capability never even reaches the
matrix.

Fail closed: a disabled capability denies; disabling is the safe direction, so the guard
can only ever tighten a downstream decision, never loosen it.

SCAFFOLDING: the switch container and its ``disable``/``enabled`` helpers are supplied;
implement ``CapabilityShutdown.guard`` (the fail-closed override) in Module 10,
Lesson 10.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from anse_harness.security.matrix import MatrixResult


@dataclass
class CapabilityShutdown:
    """A kill-switch: disabled capability ids fail closed with a loud denial."""

    disabled: set[str] = field(default_factory=set)

    def disable(self, capability_id: str) -> None:
        """Add a capability id to the disabled set (idempotent)."""
        self.disabled.add(capability_id)

    def enabled(self, capability_id: str) -> bool:
        """Report whether a capability is still enabled."""
        return capability_id not in self.disabled

    def guard(self, capability_id: str, downstream: MatrixResult) -> MatrixResult:
        """Force DENY for a disabled capability; otherwise pass ``downstream`` through.

        If ``capability_id`` is in ``self.disabled``, return a ``MatrixResult`` with
        ``MatrixDecision.DENY``, ``audit_required=True``, and a reason naming the
        capability as disabled by the kill-switch (fail closed). Otherwise return
        ``downstream`` unchanged - an enabled capability is unaffected by the switch.

        Lesson 10.6: capabilities can be disabled. Implement in Module 10.
        """
        raise NotImplementedError(
            "Module 10, Lesson 10.6: if capability_id is disabled, return a DENY "
            "MatrixResult (audit_required=True) naming the kill-switch and failing "
            "closed; otherwise return the downstream result unchanged."
        )
