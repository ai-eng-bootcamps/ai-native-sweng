"""Deterministic token estimation for context budgeting (spec Module 4, Lesson 4.6).

Real tokenizers are provider-specific and would add a heavy dependency to the
zero-dependency scripted/replay path, so the course uses a documented, deterministic
approximation instead: one token per four UTF-8 bytes, rounded up. The estimate is
byte-based, not character-based, so multi-byte text costs proportionally more - the
same direction real tokenizers err. The absolute numbers matter less than the
properties budgeting needs: the estimate is deterministic, monotonic in text size,
and cheap enough to run on every candidate context item.

SUPPLIED infrastructure: the estimator is consumed as-is, like ``models/`` and
``tracing/``; the context builder you implement in Module 4 calls it for every
budgeting decision.
"""

from __future__ import annotations

#: Documented approximation: one token per this many UTF-8 bytes, rounded up.
BYTES_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token cost of ``text`` (deterministic; see module docstring)."""
    size = len(text.encode("utf-8"))
    return (size + BYTES_PER_TOKEN - 1) // BYTES_PER_TOKEN
