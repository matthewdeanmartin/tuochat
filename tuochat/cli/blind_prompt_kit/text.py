"""Text input components."""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern
from typing import Callable

from .core import InteractionContext

Validator = Callable[[str], str | None]


@dataclass
class FreeTextInput:
    """Prompt for short free-form text."""

    prompt: str
    default: str | None = None
    required: bool = True
    secret: bool = False
    max_length: int | None = None
    pattern: str | Pattern[str] | None = None
    help_text: str | None = None
    validator: Validator | None = None

    def run(self, context: InteractionContext) -> str:
        """Run the text prompt."""
        while True:
            raw = context.ask(self.prompt, help_text=self.help_text, secret=self.secret)
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            value = text.strip()
            if not value:
                if self.default is not None:
                    return self.default
                if self.required:
                    context.fail("This field cannot be blank.")
                    continue
                return ""
            if self.max_length is not None and len(value) > self.max_length:
                context.fail(f"Enter no more than {self.max_length} characters.")
                continue
            if self.pattern is not None and re.fullmatch(self.pattern, value) is None:
                context.fail("That value is not in the expected format.")
                continue
            if self.validator is not None:
                error = self.validator(value)
                if error:
                    context.fail(error)
                    continue
            return value


@dataclass
class LargeTextInput:
    """Prompt for multiline text with explicit control commands."""

    prompt: str
    blank_line_done: bool = False
    terminator: str = "DONE"
    required: bool = False
    help_text: str | None = None

    def run(self, context: InteractionContext) -> str:
        """Collect multiline text line by line."""
        if self.blank_line_done:
            instructions = "Enter text. Blank line to finish."
        else:
            instructions = f"Enter text. Type {self.terminator} on its own line to finish."
        help_text = self.help_text or (
            "Commands here: show, show last, show summary, edit last, clear, done, back, cancel."
        )
        lines: list[str] = []
        context.say(self.prompt)
        context.say(instructions)
        while True:
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)
            if command is not None:
                if command.name == "show":
                    argument = (command.argument or "").lower()
                    if argument == "last":
                        context.say(lines[-1] if lines else "No lines yet.")
                    elif argument == "summary":
                        context.say(self.render_summary(lines))
                    else:
                        context.say(self.render_full_text(lines))
                    continue
                if command.name == "edit":
                    if not lines:
                        context.say("Nothing to edit.")
                        continue
                    removed = lines.pop()
                    context.say(f"Removed: {removed}")
                    replacement = context.io.prompt("Replacement> ")
                    literal = context.parse_raw_input(replacement)[0]
                    lines.append(literal)
                    context.say("Last line updated.")
                    continue
                if context.apply_common_command(
                    command,
                    help_text=help_text,
                    status=lambda: self.render_summary(lines),
                    summary=lambda: self.render_summary(lines),
                    details=lambda: self.render_full_text(lines),
                ):
                    continue
                if command.name == "done":
                    if lines or not self.required:
                        return self.finish(context, lines)
                    context.fail("This field cannot be blank.")
                    continue
                if command.name == "clear":
                    lines.clear()
                    context.say("Cleared.")
                    continue
            if self.blank_line_done and not text:
                if lines or not self.required:
                    return self.finish(context, lines)
                context.fail("This field cannot be blank.")
                continue
            if not self.blank_line_done and text.strip().upper() == self.terminator.upper():
                if lines or not self.required:
                    return self.finish(context, lines)
                context.fail("This field cannot be blank.")
                continue
            lines.append(text)

    def finish(self, context: InteractionContext, lines: list[str]) -> str:
        """Emit a concise completion message and return the captured text."""
        line_count = len(lines)
        noun = "line" if line_count == 1 else "lines"
        context.say(f"Saved {line_count} {noun}.")
        return "\n".join(lines)

    def render_summary(self, lines: list[str]) -> str:
        """Render a concise summary."""
        if not lines:
            return "No lines entered."
        word_count = sum(len(line.split()) for line in lines)
        noun = "line" if len(lines) == 1 else "lines"
        return f"{len(lines)} {noun}, about {word_count} words."

    def render_full_text(self, lines: list[str]) -> str:
        """Render the captured text for read-back."""
        if not lines:
            return "No text entered."
        return "\n".join(lines)
