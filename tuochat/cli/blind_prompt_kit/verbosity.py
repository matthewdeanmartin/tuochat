"""Verbosity controls for blind-first interactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verbosity(str, Enum):
    """Supported verbosity levels."""

    SILENT_MINIMAL = "silent-minimal"
    BRIEF = "brief"
    STANDARD = "standard"
    VERBOSE = "verbose"


verbosity_order = [
    Verbosity.SILENT_MINIMAL,
    Verbosity.BRIEF,
    Verbosity.STANDARD,
    Verbosity.VERBOSE,
]


@dataclass
class VerbosityController:
    """Stateful verbosity selection."""

    level: Verbosity = Verbosity.STANDARD

    def set(self, level: Verbosity | str) -> Verbosity:
        """Set the current level."""
        if isinstance(level, str):
            level = Verbosity(level)
        self.level = level
        return self.level

    def increase(self) -> Verbosity:
        """Move one step toward more detail."""
        index = verbosity_order.index(self.level)
        if index < len(verbosity_order) - 1:
            self.level = verbosity_order[index + 1]
        return self.level

    def decrease(self) -> Verbosity:
        """Move one step toward less detail."""
        index = verbosity_order.index(self.level)
        if index > 0:
            self.level = verbosity_order[index - 1]
        return self.level

    def allows_hint(self, *, essential: bool = False) -> bool:
        """Report whether a hint should be spoken."""
        if essential:
            return True
        return self.level in {Verbosity.STANDARD, Verbosity.VERBOSE}

    def allows_expansion(self) -> bool:
        """Report whether expanded details should be spoken automatically."""
        return self.level == Verbosity.VERBOSE
