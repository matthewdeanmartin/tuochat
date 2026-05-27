"""Core interaction context and component protocol."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from .adapters import BlindIO, ConsoleIO
from .commands import Command, parse_command, parse_literal_text, parse_yes_no
from .exceptions import InteractionCancelled, StepBack, StepSkip
from .verbosity import Verbosity, VerbosityController

ValueT = TypeVar("ValueT")
ValueT_co = TypeVar("ValueT_co", covariant=True)


class Component(Protocol[ValueT_co]):
    """Protocol for composable prompt components."""

    def run(self, context: InteractionContext) -> ValueT_co: ...


@dataclass
class PromptFrame:
    """Remember the most recent prompt for repeat/help commands."""

    prompt: str
    hint: str | None = None
    help_text: str | None = None


StatusProvider = Callable[[], str | None]


@dataclass
class InteractionContext:
    """Shared runtime state for prompt components."""

    io: BlindIO = field(default_factory=ConsoleIO)
    verbosity: VerbosityController = field(default_factory=VerbosityController)
    prompt_token: str = "> "
    session_state: dict[str, Any] = field(default_factory=dict)
    last_frame: PromptFrame | None = None

    def say(self, text: str) -> None:
        """Speak one line of output."""
        self.io.write(text)

    def say_lines(self, lines: Iterable[str]) -> None:
        """Speak several lines of output."""
        for line in lines:
            self.say(line)

    def fail(self, text: str) -> None:
        """Speak a corrective error message."""
        self.io.error(text)

    def ask(
        self,
        prompt: str,
        *,
        hint: str | None = None,
        help_text: str | None = None,
        secret: bool = False,
        essential_hint: bool = False,
    ) -> str:
        """Present a prompt and return the raw response."""
        self.say(prompt)
        spoken_hint = hint if hint and self.verbosity.allows_hint(essential=essential_hint) else None
        if spoken_hint:
            self.say(spoken_hint)
        self.last_frame = PromptFrame(prompt=prompt, hint=spoken_hint, help_text=help_text)
        return self.io.prompt(self.prompt_token, secret=secret)

    def repeat_last(self) -> bool:
        """Replay the last prompt."""
        if self.last_frame is None:
            self.say("Nothing to repeat.")
            return False
        self.say(self.last_frame.prompt)
        if self.last_frame.hint:
            self.say(self.last_frame.hint)
        return True

    def apply_common_command(
        self,
        command: Command,
        *,
        help_text: str | None = None,
        status: str | StatusProvider | None = None,
        summary: str | StatusProvider | None = None,
        details: str | StatusProvider | None = None,
    ) -> bool:
        """Handle global commands shared across most components."""
        if command.name == "cancel":
            raise InteractionCancelled("Interaction cancelled.")
        if command.name == "back":
            raise StepBack("Back requested.")
        if command.name == "skip":
            raise StepSkip("Skip requested.")
        if command.name == "repeat":
            self.repeat_last()
            return True
        if command.name == "help":
            frame_help = self.last_frame.help_text if self.last_frame else None
            if help_text or frame_help:
                self.say(help_text or frame_help or "")
            else:
                self.say("No extra help for this step.")
            return True
        if command.name == "more":
            level = self.verbosity.increase()
            self.say(f"Verbosity: {level.value}.")
            return True
        if command.name == "less":
            level = self.verbosity.decrease()
            self.say(f"Verbosity: {level.value}.")
            return True
        if command.name == "brief":
            self.verbosity.set(Verbosity.BRIEF)
            self.say("Verbosity: brief.")
            return True
        if command.name == "verbose":
            self.verbosity.set(Verbosity.VERBOSE)
            self.say("Verbosity: verbose.")
            return True
        if command.name == "status":
            return self.say_provider_text(status, missing="No status available.")
        if command.name == "summary":
            return self.say_provider_text(summary or status, missing="No summary available.")
        if command.name in {"show", "details"}:
            return self.say_provider_text(details or summary or status, missing="Nothing to show.")
        return False

    def say_provider_text(self, provider: str | StatusProvider | None, *, missing: str) -> bool:
        """Speak text produced by a provider."""
        if provider is None:
            self.say(missing)
            return True
        text = provider() if callable(provider) else provider
        if not text:
            self.say(missing)
            return True
        self.say(text)
        return True

    def parse_raw_input(self, raw: str) -> tuple[str, Command | None]:
        """Split escaped literal text from command input."""
        literal = parse_literal_text(raw)
        if literal is not None:
            return literal, None
        return raw, parse_command(raw)

    def ask_yes_no(self, prompt: str, *, default: bool | None = None, help_text: str | None = None) -> bool:
        """Ask a yes/no question."""
        if default is None:
            hint = "Yes or no."
        elif default:
            hint = "Yes or no. Default yes."
        else:
            hint = "Yes or no. Default no."
        while True:
            raw = self.ask(prompt, hint=hint, help_text=help_text)
            text, command = self.parse_raw_input(raw)
            if command is not None and self.apply_common_command(command, help_text=help_text):
                continue
            answer = parse_yes_no(text)
            if answer is not None:
                return answer
            if not text.strip() and default is not None:
                return default
            self.fail("Answer yes or no.")
