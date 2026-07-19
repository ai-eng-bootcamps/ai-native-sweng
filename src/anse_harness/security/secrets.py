"""Secret and environment hardening (Lesson 10.3: least privilege, secret isolation).

Three independent layers keep a credential out of the model's context and off the wire,
of which two are new here and one is reused unchanged:

1. **Environment allowlist filter** (``filter_env``): only allowlisted variables survive
   into a subprocess environment, so a ``.env`` full of credentials never reaches a tool
   or worker process (architecture-reference 58 environment filtering).
2. **Packet-level secret scan** (``scan_for_secrets``): token-shaped strings are caught
   in any outward payload before it is sent (architecture-reference 58 secret redaction).
3. **Trace redaction** (REUSED unchanged from Module 9): ``TraceEvent.sensitive_keys``
   scrubs classified payload values before they reach disk. This module adds nothing to
   it; ``tracing/jsonl.py`` is the backstop.

The detectors match INERT credential SHAPES (an ``AKIA``-prefixed AWS access key, a
``ghp_`` GitHub token, a 40-character AWS secret). The 40-character detector is
deliberately broad and can false-positive on a legitimate hash or id; the ``AKIA`` and
``ghp_`` detectors are tight. A shape match means "treat as a secret and refuse to send",
not "this authenticates something" - the training fixtures use documented non-secrets.

SCAFFOLDING: the detector table and the default allowlist are supplied; implement
``scan_for_secrets`` and ``filter_env`` in Module 10, Lesson 10.3.
"""

from __future__ import annotations

import re

#: Inert-credential SHAPE detectors: (kind, compiled pattern). Order is stable so the
#: reported kinds are deterministic.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_pat", re.compile(r"ghp_[0-9A-Za-z]{36}")),
    ("aws_secret_key", re.compile(r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])")),
)

#: Default environment allowlist: only these variables pass to a worker/sandbox
#: subprocess. Everything else - including every credential-bearing variable - is dropped
#: (deny by default carried to the process environment).
DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset({"PATH", "HOME", "LANG", "GOPATH", "GOCACHE"})


def scan_for_secrets(text: str) -> list[str]:
    """Return the kinds of secret-shaped strings found in ``text`` (packet scan).

    For each ``(kind, pattern)`` in ``SECRET_PATTERNS`` in order, if the pattern matches
    anywhere in ``text``, include ``kind`` in the result. Return the kinds in
    ``SECRET_PATTERNS`` order (deterministic); an empty list means no secret shape was
    found. A non-empty result must block the outward send.

    Lesson 10.3: secrets are not included in model context / outward actions. Implement in
    Module 10.
    """
    raise NotImplementedError(
        "Module 10, Lesson 10.3: return the SECRET_PATTERNS kinds whose pattern matches "
        "text, in table order; an empty list means clean."
    )


def filter_env(
    env: dict[str, str], allowlist: frozenset[str] = DEFAULT_ENV_ALLOWLIST
) -> dict[str, str]:
    """Drop every environment variable not on the allowlist (architecture-reference 58).

    Return a new dict containing only the ``env`` items whose key is in ``allowlist``.
    Deny by default: an allowlist that fell through to "keep" would not be a control, so a
    variable absent from the allowlist is always dropped.

    Lesson 10.3: environment filtering / secret isolation. Implement in Module 10.
    """
    raise NotImplementedError(
        "Module 10, Lesson 10.3: return only the env items whose key is in allowlist; "
        "drop everything else (deny by default)."
    )
