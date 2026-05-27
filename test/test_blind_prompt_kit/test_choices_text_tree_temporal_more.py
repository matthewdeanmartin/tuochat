"""Extra coverage for choice, text, tree, and temporal components."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tuochat.cli.blind_prompt_kit import Choice, ChoiceInput, EnumInput, InteractionContext, MultiSelectInput
from tuochat.cli.blind_prompt_kit.models import TreeNode
from tuochat.cli.blind_prompt_kit.temporal import DateInput, DurationInput, TimeInput, parse_date_text
from tuochat.cli.blind_prompt_kit.text import FreeTextInput, LargeTextInput
from tuochat.cli.blind_prompt_kit.tree import FilePicker, TreeNavigator

from .test_support import FakeIO


def test_choice_input_covers_listing_paging_defaults_and_exact_selection():
    options = [Choice(label=f"Item {index}", value=index, description=f"Option {index}") for index in range(1, 12)]
    io = FakeIO(["list", "next", "prev", "page 2", "pick 2"])
    context = InteractionContext(io=io)

    result = ChoiceInput("Pick one.", options, page_size=4).run(context)

    assert result == 6
    assert any(line.startswith("Pick one. 11 options.") for line in io.outputs)
    assert any("Items 5 to 8 of 11." in line for line in io.outputs)
    assert "Item 6 selected." in io.outputs

    default_io = FakeIO([""])
    default_context = InteractionContext(io=default_io)
    assert ChoiceInput("Default.", ["A", "B"], default="B").run(default_context) == "B"

    with pytest.raises(ValueError, match="at least one option"):
        ChoiceInput("Empty.", []).run(context)


def test_choice_input_confirm_single_match_and_enum_help():
    io = FakeIO(["sea", "yes"])
    context = InteractionContext(io=io)
    result = ChoiceInput("City.", ["Seattle", "Portland"]).run(context)

    enum_io = FakeIO([])
    enum_context = InteractionContext(io=enum_io)
    enum_input = EnumInput(
        "Severity.",
        [
            Choice(label="Low", value="low", description="minor impact"),
            Choice(label="High", value="high", description="major impact"),
        ],
    )
    enum_context.say(enum_input.help())

    assert result == "Seattle"
    assert enum_io.outputs == ["Low means minor impact.\nHigh means major impact.\nPick by number or name."]


def test_multi_select_covers_required_clear_filter_and_remove_name():
    io = FakeIO(["done", "1", "2", "remove Email", "clear", "3", "done"])
    context = InteractionContext(io=io)

    result = MultiSelectInput("Notifications.", ["Email", "SMS", "Push"], required=True).run(context)

    assert result == ["Push"]
    assert "Pick at least one item before finishing." in io.errors
    assert "Email removed. 1 selected." in io.outputs
    assert "Selections cleared." in io.outputs
    assert "Selected: Push." in io.outputs


def test_free_text_input_covers_default_pattern_and_validator():
    default_io = FakeIO([""])
    default_context = InteractionContext(io=default_io)
    assert FreeTextInput("Name?", default="Ada").run(default_context) == "Ada"

    invalid_io = FakeIO(["", "toolong", "abc", "GOOD", "OK"])
    invalid_context = InteractionContext(io=invalid_io)
    result = FreeTextInput(
        "Code?",
        required=True,
        max_length=4,
        pattern=r"[A-Z]{2,4}",
        validator=lambda value: "Reserved." if value == "GOOD" else None,
    ).run(invalid_context)

    optional_io = FakeIO([""])
    optional_context = InteractionContext(io=optional_io)
    blank = FreeTextInput("Optional?", required=False).run(optional_context)

    assert result == "OK"
    assert blank == ""
    assert invalid_context.io.errors == [
        "This field cannot be blank.",
        "Enter no more than 4 characters.",
        "That value is not in the expected format.",
        "Reserved.",
    ]


def test_large_text_input_covers_show_clear_blank_line_and_helpers():
    io = FakeIO(["show last", "show", "edit", "first", "show summary", "clear", ""])
    context = InteractionContext(io=io)

    result = LargeTextInput("Notes.", blank_line_done=True, required=False).run(context)
    helper = LargeTextInput("Helper.")

    assert result == ""
    assert "No text entered." in io.outputs
    assert "Nothing to edit." in io.outputs
    assert "No lines yet." in io.outputs
    assert helper.render_summary([]) == "No lines entered."
    assert "Cleared." in io.outputs
    assert helper.render_summary(["alpha", "beta"]) == "2 lines, about 2 words."
    assert helper.render_full_text([]) == "No text entered."


def test_tree_navigator_and_file_picker_cover_text_entry_and_directory_pick(tmp_path):
    tree = TreeNode(
        label="Root",
        children=(
            TreeNode(label="Folder", children=(TreeNode(label="Leaf", value="leaf"),)),
            TreeNode(label="Solo", value="solo"),
        ),
    )
    io = FakeIO(["folder", "leaf"])
    context = InteractionContext(io=io)

    result = TreeNavigator(root=tree).run(context)

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    picker_io = FakeIO(["pick 1"])
    picker_context = InteractionContext(io=picker_io)
    picked = FilePicker(root=tmp_path, include_directories=True).run(picker_context)

    assert result is not None
    assert result.value == "leaf"
    assert picked is not None
    assert picked.path == empty_dir


def test_temporal_inputs_cover_step_modes_and_direct_retry():
    reference_date = date(2026, 4, 10)
    parsed_today, _ = parse_date_text("today", reference=reference_date)
    parsed_tomorrow, _ = parse_date_text("tomorrow", reference=reference_date)

    date_io = FakeIO(["step", "NotAMonth", "April", "11", "2026"])
    date_context = InteractionContext(io=date_io)
    date_value = DateInput("Start?", reference_date=reference_date).run(date_context)

    time_io = FakeIO(["25:00", "step", "3", "30", "maybe", "4", "45", "pm"])
    time_context = InteractionContext(io=time_io)
    time_value = TimeInput("Time?").run(time_context)

    duration_io = FakeIO(["invalid", "45 minutes"])
    duration_context = InteractionContext(io=duration_io)
    duration_value = DurationInput("Length?").run(duration_context)

    assert parsed_today == reference_date
    assert parsed_tomorrow == reference_date + timedelta(days=1)
    assert date_value == date(2026, 4, 11)
    assert "Say the month name, like April." in date_io.errors
    assert time_value.hour == 16 and time_value.minute == 45
    assert "Answer AM or PM." in time_io.errors
    assert duration_value == timedelta(minutes=45)
    assert "Enter a duration like 30 minutes, 2h, or 1 hour 15 minutes." in duration_io.errors
