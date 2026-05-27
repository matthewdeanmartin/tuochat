"""Additional tests for command parsing, context behavior, models, and adapters."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

import tuochat.cli.io as io_module
from tuochat.cli.blind_prompt_kit import Choice, ConsoleIO, InteractionContext, SummaryField, TableColumn, Verbosity
from tuochat.cli.blind_prompt_kit.commands import Command, parse_command, parse_literal_text, parse_yes_no
from tuochat.cli.blind_prompt_kit.core import PromptFrame
from tuochat.cli.blind_prompt_kit.exceptions import InteractionCancelled, StepBack, StepSkip
from tuochat.cli.blind_prompt_kit.models import DateRange, NumberRange, render_date_value
from tuochat.cli.blind_prompt_kit.verbosity import VerbosityController

from .test_support import FakeIO


def test_console_io_uses_backend_for_multiline_and_support_flag(monkeypatch):
    backend = SimpleNamespace(
        supports_multiline=True,
        read_multiline=lambda prompt: f"multi:{prompt}",
    )
    monkeypatch.setattr(io_module, "active_backend", backend)

    adapter = ConsoleIO()

    assert adapter.supports_multiline is True
    assert adapter.prompt_multiline("Notes: ") == "multi:Notes: "


def test_console_io_write_and_error_emit_to_standard_streams(capsys):
    adapter = ConsoleIO()

    adapter.write("hello")
    adapter.error("oops")

    captured = capsys.readouterr()
    assert captured.out == "hello\n"
    assert captured.err == "oops\n"


def test_command_helpers_cover_aliases_arguments_and_literals():
    assert parse_command("?") == Command(name="help", argument=None, raw="?")
    assert parse_command("pick 2") == Command(name="pick", argument="2", raw="pick 2")
    assert parse_command("help now") is None
    assert parse_command("plain text") is None
    assert parse_literal_text(r"\help") == "help"
    assert parse_literal_text("text use help") == "use help"
    assert parse_literal_text("literal keep this") == "keep this"
    assert parse_yes_no("confirm") is True
    assert parse_yes_no("false") is False
    assert parse_yes_no("maybe") is None


def test_interaction_context_ask_repeat_and_common_commands():
    io = FakeIO(["answer", "second"])
    context = InteractionContext(io=io, verbosity=VerbosityController(level=Verbosity.BRIEF))

    result = context.ask("Project?", hint="Short name.", help_text="Help here.")

    assert result == "answer"
    assert io.outputs == ["Project?"]
    assert context.repeat_last() is True
    assert io.outputs[-1] == "Project?"

    context.ask("Secret?", hint="Always speak this.", essential_hint=True)
    assert io.outputs[-2:] == ["Secret?", "Always speak this."]

    assert context.apply_common_command(Command("help"), help_text="Explicit help.") is True
    assert io.outputs[-1] == "Explicit help."

    context.last_frame = PromptFrame(prompt="Question", hint="Hint", help_text="Frame help.")
    assert context.apply_common_command(Command("repeat")) is True
    assert io.outputs[-2:] == ["Question", "Hint"]

    assert context.apply_common_command(Command("more")) is True
    assert context.apply_common_command(Command("less")) is True
    assert context.apply_common_command(Command("brief")) is True
    assert context.apply_common_command(Command("verbose")) is True
    assert context.apply_common_command(Command("status"), status="Ready.") is True
    assert context.apply_common_command(Command("summary"), summary=lambda: "Summary text.") is True
    assert context.apply_common_command(Command("show"), details=lambda: "Detail text.") is True
    assert context.apply_common_command(Command("details"), details=None) is True
    assert io.outputs[-4:] == ["Ready.", "Summary text.", "Detail text.", "Nothing to show."]


def test_interaction_context_raises_for_cancel_back_and_skip():
    context = InteractionContext(io=FakeIO([]))

    with pytest.raises(InteractionCancelled):
        context.apply_common_command(Command("cancel"))

    with pytest.raises(StepBack):
        context.apply_common_command(Command("back"))

    with pytest.raises(StepSkip):
        context.apply_common_command(Command("skip"))


def test_interaction_context_ask_yes_no_handles_retry_and_default():
    io = FakeIO(["maybe", ""])
    context = InteractionContext(io=io)

    result = context.ask_yes_no("Proceed?", default=True, help_text="Say yes or no.")

    assert result is True
    assert io.errors == ["Answer yes or no."]
    assert "Yes or no. Default yes." in io.outputs


def test_model_helpers_render_user_facing_text():
    choice = Choice(label="Primary", value=1, spoken="First choice")
    number_range = NumberRange(Decimal("1.5"), None)
    date_range = DateRange(None, date(2026, 4, 11))
    table_column = TableColumn(name="status", label="Status", aliases=("state",))
    formatted_column = TableColumn(name="total", formatter=lambda value: f"${value:.2f}")

    assert choice.display_text() == "First choice"
    assert number_range.render() == "1.5 or more."
    assert date_range.render() == "Through April 11, 2026."
    assert render_date_value(date(2026, 1, 2)) == "January 2, 2026"
    assert table_column.render({"status": "Ready"}) == "Ready"
    assert table_column.render({"status": None}) == "blank"
    assert table_column.matches("state") is True
    assert formatted_column.render({"total": 12}) == "$12.00"
    assert SummaryField(name="Owner", value="Mina").render() == "Owner: Mina"
    assert SummaryField(name="Notes", value="").render() == "Notes: blank"
    assert SummaryField(name="Amount", value=2, renderer=lambda value: f"${value}").render() == "Amount: $2"


def test_verbosity_controller_moves_between_levels():
    controller = VerbosityController()

    assert controller.set("brief") == Verbosity.BRIEF
    assert controller.decrease() == Verbosity.SILENT_MINIMAL
    assert controller.decrease() == Verbosity.SILENT_MINIMAL
    assert controller.increase() == Verbosity.BRIEF
    assert controller.increase() == Verbosity.STANDARD
    assert controller.increase() == Verbosity.VERBOSE
    assert controller.increase() == Verbosity.VERBOSE
    assert controller.allows_hint() is True
    assert controller.allows_hint(essential=True) is True
    assert controller.allows_expansion() is True
