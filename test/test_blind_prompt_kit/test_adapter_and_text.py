"""Tests for adapter and text-oriented components."""

from __future__ import annotations

from tuochat.cli.blind_prompt_kit import ConsoleIO, FreeTextInput, InteractionContext, LargeTextInput
from tuochat.cli.io import prompt_handler

from .test_support import FakeIO


def test_console_io_uses_io_prompt_handler():
    adapter = ConsoleIO()

    with prompt_handler(lambda prompt, secret=False: "hooked"):
        assert adapter.prompt("Prompt: ") == "hooked"


def test_free_text_input_can_escape_global_command_words():
    io = FakeIO(["help", "literal help"])
    context = InteractionContext(io=io)

    result = FreeTextInput("Project name?", help_text="Enter a short name.").run(context)

    assert result == "help"
    assert "Enter a short name." in io.outputs


def test_large_text_input_supports_editing_last_line_and_done():
    io = FakeIO(["first line", "second line", "edit", "replacement line", "done"])
    context = InteractionContext(io=io)

    result = LargeTextInput("Notes.").run(context)

    assert result == "first line\nreplacement line"
    assert "Last line updated." in io.outputs
    assert "Saved 2 lines." in io.outputs
