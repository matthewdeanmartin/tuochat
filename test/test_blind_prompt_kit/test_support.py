"""Shared test helpers for blind_prompt_kit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeIO:
    """Simple scripted I/O for component tests."""

    responses: list[str]
    supports_multiline: bool = False
    outputs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    prompts: list[tuple[str, bool]] = field(default_factory=list)
    index: int = 0

    def prompt(self, prompt: str, *, secret: bool = False) -> str:
        """Return the next scripted response."""
        self.prompts.append((prompt, secret))
        if self.index >= len(self.responses):
            raise AssertionError("Ran out of scripted input.")
        response = self.responses[self.index]
        self.index += 1
        return response

    def prompt_multiline(self, prompt: str) -> str | None:
        """This test double does not provide multiline editing."""
        self.prompts.append((prompt, False))
        return None

    def write(self, text: str) -> None:
        """Capture normal output."""
        self.outputs.append(text)

    def error(self, text: str) -> None:
        """Capture error output."""
        self.errors.append(text)


class ScriptedComponent:
    """Component stub for form tests."""

    def __init__(self, results: list[Any]):
        self.results = list(results)

    def run(self, context):  # noqa: ANN001
        """Return or raise the next scripted result."""
        if not self.results:
            raise AssertionError("Ran out of scripted component results.")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
