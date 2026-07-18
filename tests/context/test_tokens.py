"""The supplied deterministic token estimator (Module 4, Lesson 4.6).

The estimator is SUPPLIED infrastructure (one token per four UTF-8 bytes, rounded
up), so these tests run in the default suite: they pin the properties budgeting
relies on - determinism, byte-based counting, and monotonicity in text size.
"""

from anse_harness.context.tokens import BYTES_PER_TOKEN, estimate_tokens


def test_empty_text_costs_nothing() -> None:
    assert estimate_tokens("") == 0


def test_four_ascii_bytes_per_token_rounded_up() -> None:
    assert BYTES_PER_TOKEN == 4
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_multibyte_text_counts_bytes_not_characters() -> None:
    # Four two-byte characters are eight bytes: two tokens, not one.
    assert estimate_tokens("éééé") == 2


def test_estimate_is_monotonic_in_text_size() -> None:
    text = "reservation hold lifetime"
    assert estimate_tokens(text) <= estimate_tokens(text + " and expiry rules")
