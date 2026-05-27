"""Control-flow exceptions for blind prompt interactions."""

from __future__ import annotations


class BlindPromptError(Exception):
    """Base exception for blind prompt interactions."""


class InteractionCancelled(BlindPromptError):
    """Raised when the user cancels the current interaction."""


class StepBack(BlindPromptError):
    """Raised when the user wants to move to the previous step."""


class StepSkip(BlindPromptError):
    """Raised when the user wants to skip the current step."""
