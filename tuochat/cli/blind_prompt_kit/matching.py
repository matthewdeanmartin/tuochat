"""Matching helpers for choice and search components."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .models import Choice

ValueT = TypeVar("ValueT")
ChoiceT = TypeVar("ChoiceT", bound=Choice[Any])


def normalize_text(text: str) -> str:
    """Normalize free-form text for matching."""
    return " ".join(text.lower().strip().split())


def choice_terms(choice: Choice[ValueT]) -> tuple[str, ...]:
    """Return normalized searchable terms for a choice."""
    return tuple(normalize_text(value) for value in [choice.label, *choice.aliases])


@dataclass(frozen=True)
class ChoiceMatch(Generic[ValueT]):
    """A ranked choice match."""

    choice: Choice[ValueT]
    score: tuple[int, int, int]


def rank_choices(query: str, choices: Sequence[ChoiceT]) -> list[ChoiceT]:
    """Return choices ordered by exact, prefix, and substring quality."""
    normalized_query = normalize_text(query)
    if not normalized_query:
        return list(choices)
    scored: list[tuple[tuple[int, int, int], ChoiceT]] = []
    for index, choice in enumerate(choices):
        terms = choice_terms(choice)
        exact = any(term == normalized_query for term in terms)
        prefix = any(term.startswith(normalized_query) for term in terms)
        substring = any(normalized_query in term for term in terms)
        if not (exact or prefix or substring):
            continue
        if exact:
            rank = (0, 0, index)
        elif prefix:
            rank = (1, min(term.find(normalized_query) for term in terms if term.startswith(normalized_query)), index)
        else:
            rank = (2, min(term.find(normalized_query) for term in terms if normalized_query in term), index)
        scored.append((rank, choice))
    return [choice for _, choice in sorted(scored, key=lambda item: item[0])]
