"""I/O adapters for blind-first prompts."""

from __future__ import annotations

from collections.abc import Callable
import sys
from dataclasses import dataclass
from typing import Protocol


class BlindIO(Protocol):
    """Minimal I/O protocol for the package."""

    @property
    def supports_multiline(self) -> bool: ...

    def prompt(self, prompt: str, *, secret: bool = False) -> str: ...

    def prompt_multiline(self, prompt: str) -> str | None: ...

    def write(self, text: str) -> None: ...

    def error(self, text: str) -> None: ...


@dataclass
class ConsoleIO:
    """Default terminal I/O adapter that depends only on tuochat.cli.io."""

    def prompt(self, prompt: str, *, secret: bool = False) -> str:
        """Read a line of input."""
        from tuochat.cli.io import read_prompt

        return read_prompt(prompt, secret=secret)

    def prompt_multiline(self, prompt: str) -> str | None:
        """Read multiline input when the current backend supports it."""
        from tuochat.cli.io import get_backend

        backend = get_backend()
        multiline_reader = getattr(backend, "read_multiline", None)
        if not callable(multiline_reader):
            return None
        return call_multiline_reader(multiline_reader, prompt)

    def write(self, text: str) -> None:
        """Write to standard output."""
        print(text)

    def error(self, text: str) -> None:
        """Write to standard error."""
        print(text, file=sys.stderr)

    @property
    def supports_multiline(self) -> bool:
        """Report whether multiline entry is available."""
        from tuochat.cli.io import get_backend

        backend = get_backend()
        return bool(getattr(backend, "supports_multiline", False))


def call_multiline_reader(reader: Callable[[str], str | None], prompt: str) -> str | None:
    """Invoke a validated multiline reader."""
    return reader(prompt)
