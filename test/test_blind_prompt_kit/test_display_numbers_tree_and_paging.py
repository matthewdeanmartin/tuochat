"""Additional tests for display, numeric prompts, trees, and paging."""

from __future__ import annotations

from decimal import Decimal

from tuochat.cli.blind_prompt_kit import (
    InteractionContext,
    KeyValueViewer,
    ListViewer,
    LongTextReader,
    NumberRangeInput,
    SummaryField,
    TableColumn,
    TableViewer,
    TextDisplay,
    TreeNavigator,
    TreeNode,
)
from tuochat.cli.blind_prompt_kit.models import FilePick
from tuochat.cli.blind_prompt_kit.numbers import DecimalInput, IntegerInput, YesNoInput, render_decimal
from tuochat.cli.blind_prompt_kit.pagination import Pager
from tuochat.cli.blind_prompt_kit.tree import FilePicker

from .test_support import FakeIO


def test_text_and_key_value_viewers_speak_content():
    io = FakeIO([])
    context = InteractionContext(io=io)

    TextDisplay("Status ready").show(context)
    KeyValueViewer(title="Record", fields=[SummaryField(name="Owner", value="Ada")]).show(context)

    assert io.outputs == ["Status ready", "Record", "Owner: Ada"]


def test_list_viewer_supports_navigation_filter_and_pick():
    io = FakeIO(["next", "item 2", "find ta", "1"])
    context = InteractionContext(io=io)
    viewer = ListViewer("Cities", ["Austin", "Boston", "Delta", "Tampa"], page_size=2, allow_pick=True)

    result = viewer.run(context)

    assert result == "Delta"
    assert any("Showing 3 to 4." in line for line in io.outputs)
    assert "Tampa" in io.outputs
    assert "2 matches." in io.outputs
    assert "Delta selected." in io.outputs


def test_long_text_reader_runs_across_modes_and_find():
    text = "Alpha starts here.\n\nBeta follows next.\n\nGamma closes the note."
    io = FakeIO(["summary", "sentence mode", "next", "find gamma", "line mode", ""])
    context = InteractionContext(io=io)

    LongTextReader("Readme", text=text).run(context)

    assert any(line == "Summary: Alpha starts here." for line in io.outputs)
    assert any(line.startswith("Sentence 2 to 2 of 3:") for line in io.outputs)
    assert any("Gamma closes the note." in line for line in io.outputs)
    assert any(line.startswith("Line 1 to 1 of 3:") for line in io.outputs)


def test_table_viewer_covers_focus_cells_and_filter():
    rows = [
        {"status": "Queued", "total": 5},
        {"status": "Paid", "total": 12},
    ]
    columns = [
        TableColumn(name="status", label="Status"),
        TableColumn(name="total", label="Total"),
    ]
    io = FakeIO(["columns", "focus total", "cell row 2 total", "find paid", "row 2", ""])
    context = InteractionContext(io=io)

    TableViewer("Orders", rows=rows, columns=columns).run(context)

    assert "Columns: Status, Total" in io.outputs
    assert "Columns in focus: total." in io.outputs
    assert "Cell. Row 2, Total: 12." in io.outputs
    assert "1 matching rows." in io.outputs
    assert any(line == "Row 2. 12." for line in io.outputs)


def test_integer_decimal_yes_no_and_range_inputs_validate_and_parse():
    integer_io = FakeIO(["bad", "11", "5"])
    integer_context = InteractionContext(io=integer_io)
    integer = IntegerInput("How many?", minimum=1, maximum=10).run(integer_context)

    decimal_io = FakeIO(["4.999", "2.5"])
    decimal_context = InteractionContext(io=decimal_io)
    decimal_value = DecimalInput(
        "Budget?",
        minimum=Decimal("1"),
        maximum=Decimal("3"),
        normalize_output=True,
    ).run(decimal_context)

    yes_no_io = FakeIO(["", "yes"])
    yes_no_context = InteractionContext(io=yes_no_io)
    answer = YesNoInput("Continue?", default=False).run(yes_no_context)

    range_io = FakeIO(["step", "10", "5", "20"])
    range_context = InteractionContext(io=range_io)
    number_range = NumberRangeInput("Range?").run(range_context)

    assert integer == 5
    assert integer_io.errors == [
        "Enter a whole number from 1 to 10.",
        "Enter a whole number from 1 to 10.",
    ]
    assert decimal_value == Decimal("2.5")
    assert "Budget: 2.50" in decimal_io.outputs
    assert answer is False
    assert number_range.render() == "10 to 20."
    assert "Maximum must be greater than or equal to minimum." in range_io.errors


def test_numeric_helpers_and_pager_cover_direct_methods():
    pager = Pager(["a", "b", "c", "d", "e"], page_size=2)

    assert render_decimal(Decimal("2.500")) == "2.5"
    assert NumberRangeInput("Range?").parse_direct("under 50").render() == "Up to 50."
    assert NumberRangeInput("Range?").parse_direct("5+").render() == "5 or more."
    assert NumberRangeInput("Range?").parse_direct("nope") is None

    assert pager.total_pages() == 3
    assert pager.current().items == ["a", "b"]
    assert pager.next().items == ["c", "d"]
    assert pager.last().items == ["e"]
    assert pager.prev().items == ["c", "d"]
    assert pager.go_to(10).items == ["e"]
    assert pager.resize(3).items == ["d", "e"]


def test_tree_navigator_handles_back_path_open_and_pick():
    tree = TreeNode(
        label="Root",
        children=(
            TreeNode(label="Projects", children=(TreeNode(label="Alpha", value="alpha"),)),
            TreeNode(label="Archive", value="archive"),
        ),
    )
    io = FakeIO(["back", "path", "open 1", "pick 1"])
    context = InteractionContext(io=io)

    result = TreeNavigator(root=tree).run(context)

    assert result is not None
    assert result.label == "Alpha"
    assert "Already at the root." in io.errors
    assert "Path: Root" in io.outputs
    assert "Alpha selected." in io.outputs


def test_file_picker_traverses_directories_and_returns_selected_file(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    selected_path = docs_dir / "guide.txt"
    selected_path.write_text("guide", encoding="utf-8")
    (tmp_path / "readme.md").write_text("top", encoding="utf-8")

    io = FakeIO(["back", "list", "open 1", "pick 1"])
    context = InteractionContext(io=io)

    result = FilePicker(root=tmp_path).run(context)

    assert result == FilePick(selected_path)
    assert "Already at the root." in io.errors
    assert any(line.startswith("File picker. Path:") for line in io.outputs)
    assert "guide.txt selected." in io.outputs
