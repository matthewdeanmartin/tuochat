"""Shared data models for the blind prompt kit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

ValueT = TypeVar("ValueT")


def render_date_value(value: date) -> str:
    """Render a date in a speech-friendly format."""
    return f"{value.strftime('%B')} {value.day}, {value.year}"


@dataclass(frozen=True)
class Choice(Generic[ValueT]):
    """A selectable choice."""

    label: str
    value: ValueT
    aliases: tuple[str, ...] = ()
    description: str | None = None
    spoken: str | None = None

    def display_text(self) -> str:
        """Return the preferred spoken text."""
        return self.spoken or self.label


@dataclass(frozen=True)
class NumberRange:
    """A numeric range."""

    minimum: Decimal | None
    maximum: Decimal | None

    def render(self) -> str:
        """Render the range concisely."""
        if self.minimum is None and self.maximum is None:
            return "Any value."
        if self.minimum is None:
            return f"Up to {self.maximum}."
        if self.maximum is None:
            return f"{self.minimum} or more."
        return f"{self.minimum} to {self.maximum}."


@dataclass(frozen=True)
class DateRange:
    """A date range."""

    start: date | None
    end: date | None

    def render(self) -> str:
        """Render the range concisely."""
        if self.start is None:
            if self.end is None:
                return "Any date."
            return f"Through {render_date_value(self.end)}."
        if self.end is None:
            return f"From {render_date_value(self.start)} onward."
        return f"{render_date_value(self.start)} through {render_date_value(self.end)}."


@dataclass(frozen=True)
class TableColumn:
    """Column metadata for table viewers."""

    name: str
    label: str | None = None
    aliases: tuple[str, ...] = ()
    formatter: Callable[[Any], str] | None = None

    def render(self, row: dict[str, Any]) -> str:
        """Render a row value for this column."""
        value = row.get(self.name)
        if self.formatter is not None:
            return self.formatter(value)
        if value is None:
            return "blank"
        return str(value)

    def matches(self, candidate: str) -> bool:
        """Return whether a spoken name matches this column."""
        normalized = candidate.strip().lower()
        names = [self.name, self.label or self.name, *self.aliases]
        return any(normalized == name.lower() for name in names)


@dataclass(frozen=True)
class TreeNode(Generic[ValueT]):
    """A simple tree node."""

    label: str
    value: ValueT | None = None
    children: tuple[TreeNode[ValueT], ...] = ()


@dataclass(frozen=True)
class FilePick:
    """A file selection."""

    path: Path


@dataclass
class SummaryField:
    """Small reusable summary item."""

    name: str
    value: Any = None
    blank_label: str = "blank"
    renderer: Callable[[Any], str] | None = None

    def render(self) -> str:
        """Render the field for spoken summaries."""
        if self.value is None or self.value == "":
            return f"{self.name}: {self.blank_label}"
        if self.renderer is not None:
            return f"{self.name}: {self.renderer(self.value)}"
        return f"{self.name}: {self.value}"


@dataclass
class ComponentState:
    """Simple state bag for components that want session-local memory."""

    values: dict[str, Any] = field(default_factory=dict)
