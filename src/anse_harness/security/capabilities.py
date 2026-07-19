"""Capability classes, repository classification, and the decision vocabulary (Module 10).

Module 10 consolidates the safety controls the earlier modules introduced. Two axes
govern every consequential action:

* the **capability class** of the action (canonical-reference section 6: the six
  side-effect classes 0-5, from pure observation to prohibited), and
* the **classification of the repository** the action targets (architecture-reference
  section 26 context trust, narrowed here to the course's own targets vs. an untrusted
  external repository).

The policy matrix (``matrix.py``) is a total function of those two axes. This module
supplies the shared vocabulary; it is SUPPLIED scaffolding, identical between the public
package and the hidden reference. See ``policy/commands.py`` for the scaffolding
convention.
"""

from __future__ import annotations

from enum import StrEnum


class CapabilityClass(StrEnum):
    """Side-effect classes 0-5 (canonical-reference section 6).

    The class is the ``side_effect_class`` field of a tool contract; it orders actions
    by escalating consequence and drives the default policy decision.
    """

    OBSERVATION = "class-0-observation"
    LOCAL_REVERSIBLE = "class-1-local-reversible"
    LOCAL_CONSEQUENTIAL = "class-2-local-consequential"
    EXTERNAL_REVERSIBLE = "class-3-external-reversible"
    EXTERNAL_CONSEQUENTIAL = "class-4-external-consequential"
    PROHIBITED = "class-5-prohibited"


class RepoClassification(StrEnum):
    """Repository trust classification (Lesson 10.4; D15 scope: the course targets only).

    The two bookit targets the course operates on are trusted-internal; the adversarial
    minefield is untrusted-external. Untrusted-external never receives a more permissive
    decision than trusted-internal for the same capability (the matrix is monotone).
    """

    TRUSTED_INTERNAL = "trusted-internal"
    UNTRUSTED_EXTERNAL = "untrusted-external"


#: The repository-classification registry (D15: classify the three course targets only;
#: keyed by the bare repository name so a clone directory maps to a classification). Any
#: repository not listed here is treated as untrusted-external by ``classify_repo`` -
#: an unknown repository is untrusted by default, never trusted by omission.
REPO_REGISTRY: dict[str, RepoClassification] = {
    "ai-native-sweng-bookit": RepoClassification.TRUSTED_INTERNAL,
    "ai-native-sweng-bookit-platform": RepoClassification.TRUSTED_INTERNAL,
    "ai-native-sweng-minefield": RepoClassification.UNTRUSTED_EXTERNAL,
}


def classify_repo(repo_name: str) -> RepoClassification:
    """Classify a repository by its bare name, defaulting UNKNOWN to untrusted-external.

    Deny by default carried to trust: a repository the registry does not name is treated
    as untrusted-external, so an unregistered target can never be handled more
    permissively than a known trusted one.
    """
    return REPO_REGISTRY.get(repo_name, RepoClassification.UNTRUSTED_EXTERNAL)


class MatrixDecision(StrEnum):
    """The three consolidated policy-matrix decisions (Lesson 10.4).

    Coarser than the command engine's four outcomes on purpose: the matrix composes the
    engine's ``allow_with_validation`` into ``allow`` and its ``require_approval`` into
    ``approve``, so the matrix layer speaks one vocabulary across commands, tools, and
    integrations. Ordered by restrictiveness: ``allow`` < ``approve`` < ``deny``.
    """

    ALLOW = "allow"
    APPROVE = "approve"
    DENY = "deny"
