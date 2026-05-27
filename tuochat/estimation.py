"""Token and cost estimation — pure functions, no I/O."""

from __future__ import annotations

import math
import re
import unicodedata

from tuochat.constants import INPUT_COST_PER_MILLION_TOKENS, OUTPUT_COST_PER_MILLION_TOKENS


def estimate_tokens(text: str) -> int:
    """Estimate tokens very roughly from character count."""
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, (len(stripped) + 3) // 4)


def estimate_token_cost(input_tokens: int, output_tokens: int) -> tuple[float, float, float]:
    """Estimate dollar costs from token counts."""
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_MILLION_TOKENS
    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_MILLION_TOKENS
    return input_cost, output_cost, input_cost + output_cost


def format_cost(value: float) -> str:
    """Format a dollar cost value.

    >= $0.01: show as $X.XX (cents precision).
    < $0.01: show 2 significant digits (e.g. $0.0034, $0.00056).
    """
    if value >= 0.01:
        return f"${value:.2f}"
    if value == 0.0:
        return "$0.00"
    magnitude = math.floor(math.log10(abs(value)))
    decimal_places = -magnitude + 1
    return f"${value:.{decimal_places}f}"


def format_quantity(value: int | float, *, decimals: int | None = None) -> str:
    """Format numeric quantities with grouping separators."""
    if isinstance(value, int):
        return f"{value:,}"
    if decimals is None:
        decimals = 0 if value.is_integer() else 1
    return f"{value:,.{decimals}f}"


def word_count(text: str) -> int:
    """Count words in a lightweight, terminal-friendly way."""
    return len(re.findall(r"\S+", text))


def word_count_limited(text: str) -> int:
    """Count whitespace-separated words in a short user input."""
    return len(text.split())


def substantive_char_count(text: str) -> int:
    """Count characters that are neither whitespace nor punctuation."""
    count = 0
    for char in text:
        if char.isspace():
            continue
        if unicodedata.category(char).startswith("P"):
            continue
        count += 1
    return count
