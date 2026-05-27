"""Tests for token and cost estimation helpers."""

from __future__ import annotations

from tuochat.estimation import (
    estimate_token_cost,
    estimate_tokens,
    format_cost,
    format_quantity,
    substantive_char_count,
    word_count,
    word_count_limited,
)


def test_estimate_tokens_treats_blank_input_as_zero():
    """Blank or whitespace-only text should estimate to zero tokens."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("   ") == 0
    assert estimate_tokens("\n\t") == 0


def test_estimate_tokens_rounds_up_by_character_chunks():
    """Non-empty text should use the rough 4-chars-per-token heuristic."""
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_estimate_token_cost_returns_input_output_and_total_costs():
    """Per-million pricing should be applied independently and summed."""
    input_cost, output_cost, total_cost = estimate_token_cost(1_000_000, 2_000_000)

    assert input_cost == 3.0
    assert output_cost == 30.0
    assert total_cost == 33.0


def test_format_cost_uses_fixed_cents_for_one_cent_or_more():
    """Normal dollar amounts should render with two decimal places."""
    assert format_cost(0.01) == "$0.01"
    assert format_cost(1.234) == "$1.23"


def test_format_cost_preserves_significant_digits_for_tiny_values():
    """Sub-cent values should keep enough precision to stay readable."""
    assert format_cost(0.0) == "$0.00"
    assert format_cost(0.0034) == "$0.0034"
    assert format_cost(0.00056) == "$0.00056"


def test_format_quantity_adds_grouping_separators():
    """Large counts and decimal summaries should render with commas."""
    assert format_quantity(12_345) == "12,345"
    assert format_quantity(12_345.625, decimals=1) == "12,345.6"


def test_word_count_uses_non_whitespace_chunks():
    """Word counting should treat repeated spaces and newlines as separators."""
    assert word_count("") == 0
    assert word_count("hello world") == 2
    assert word_count("hello  world\ntest") == 3


def test_word_count_limited_uses_split_for_short_inputs():
    """The limited counter should match straightforward split behavior."""
    assert word_count_limited("") == 0
    assert word_count_limited("one two three") == 3


def test_substantive_char_count_skips_whitespace_and_punctuation():
    """Only letters, digits, and other substantive characters should count."""
    assert substantive_char_count("Hi, there!") == 7
    assert substantive_char_count("A B\tC\n.") == 3
