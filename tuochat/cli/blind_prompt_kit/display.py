"""Display and review components."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable

from .core import InteractionContext
from .matching import normalize_text
from .models import SummaryField, TableColumn
from .pagination import Page, Pager


@dataclass
class TextDisplay:
    """Display a short value or status."""

    text: str

    def show(self, context: InteractionContext) -> None:
        """Display the text."""
        context.say(self.text)


@dataclass
class KeyValueViewer:
    """Display one record as key-value pairs."""

    title: str | None
    fields: Sequence[SummaryField]

    def show(self, context: InteractionContext) -> None:
        """Display the record."""
        if self.title:
            context.say(self.title)
        context.say_lines(field.render() for field in self.fields)


@dataclass
class ListViewer:
    """Browse a list with paging and filtering."""

    title: str
    items: Sequence[Any]
    renderer: Callable[[Any], str] = str
    page_size: int = 6
    allow_pick: bool = False

    def run(self, context: InteractionContext) -> Any | None:
        """Run the viewer."""
        visible = list(self.items)
        pager = Pager(visible, page_size=self.page_size)
        context.say(self.start_text(pager))
        if visible:
            context.say(self.page_text(pager.current()))
        while True:
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)

            def status_snapshot(pager_snapshot=pager) -> str:
                return self.start_text(pager_snapshot)

            def details_snapshot(pager_snapshot=pager) -> str:
                return self.page_text(pager_snapshot.current())

            if command is not None:
                if context.apply_common_command(
                    command,
                    help_text="Commands here: next, prev, first, last, count, find, item, and pick when enabled.",
                    status=status_snapshot,
                    summary=status_snapshot,
                    details=details_snapshot,
                ):
                    continue
                if command.name == "next":
                    context.say(self.page_text(pager.next()))
                    continue
                if command.name == "prev":
                    context.say(self.page_text(pager.prev()))
                    continue
                if command.name == "first":
                    context.say(self.page_text(pager.first()))
                    continue
                if command.name == "last":
                    context.say(self.page_text(pager.last()))
                    continue
                if command.name == "count":
                    context.say(f"{len(visible)} items.")
                    continue
                if command.name == "item" and command.argument and command.argument.isdigit():
                    page = pager.current()
                    index = int(command.argument) - 1
                    if 0 <= index < len(page.items):
                        context.say(self.renderer(page.items[index]))
                    else:
                        context.fail("Item number out of range.")
                    continue
                if command.name in {"find", "filter"} and command.argument:
                    visible = self.filter_items(command.argument)
                    pager = Pager(visible, page_size=pager.page_size)
                    if not visible:
                        context.say(f'No matches for "{command.argument}".')
                    else:
                        context.say(f"{len(visible)} matches.")
                        context.say(self.page_text(pager.current()))
                    continue
            if not self.allow_pick:
                if not text.strip():
                    return None
                context.fail("Use list commands here.")
                continue
            page = pager.current()
            if text.strip().isdigit():
                index = int(text.strip()) - 1
                if 0 <= index < len(page.items):
                    choice = page.items[index]
                    context.say(f"{self.renderer(choice)} selected.")
                    return choice
            context.fail("Pick a listed number.")

    def filter_items(self, query: str) -> list[Any]:
        """Filter by rendered text."""
        normalized = normalize_text(query)
        return [item for item in self.items if normalized in normalize_text(self.renderer(item))]

    def start_text(self, pager: Pager[Any]) -> str:
        """Render the opening status."""
        count = len(pager.items)
        if count == 0:
            return f"{self.title}. No items."
        return f"{self.title}. {count} items."

    def page_text(self, page) -> str:
        """Render a page of items."""
        if not page.items:
            return "No items."
        lines = []
        if page.total_items > len(page.items):
            lines.append(f"Showing {page.start_index + 1} to {page.end_index}.")
        for index, item in enumerate(page.items, start=1):
            lines.append(f"{index}. {self.renderer(item)}")
        return "\n".join(lines)


@dataclass
class LongTextReader:
    """Read long text in summary, paragraph, sentence, or line mode."""

    title: str
    text: str
    summary: str | None = None
    chunk_mode: str = "paragraph"
    chunk_size: int = 1

    def run(self, context: InteractionContext) -> None:
        """Run the reader."""
        chunks = self.make_chunks(self.chunk_mode)
        pager = Pager(chunks, page_size=max(1, self.chunk_size))
        context.say(self.header_text())
        context.say(self.current_text(pager.current()))
        while True:
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)

            def details_snapshot(pager_snapshot: Pager[str] = pager) -> str:
                return self.current_text(pager_snapshot.current())

            if command is not None:
                if context.apply_common_command(
                    command,
                    help_text="Commands here: next, prev, jump 3, summary, full, sentence mode, paragraph mode, line mode, find.",
                    status=self.header_text,
                    summary=self.summary_text,
                    details=details_snapshot,
                ):
                    continue
                if command.name == "next":
                    context.say(self.current_text(pager.next()))
                    continue
                if command.name == "prev":
                    context.say(self.current_text(pager.prev()))
                    continue
                if command.name == "first":
                    context.say(self.current_text(pager.first()))
                    continue
                if command.name == "last":
                    context.say(self.current_text(pager.last()))
                    continue
                if command.name == "jump" and command.argument and command.argument.isdigit():
                    context.say(self.current_text(pager.go_to(int(command.argument))))
                    continue
                if command.name == "full":
                    context.say(self.text)
                    continue
                if command.name == "more":
                    self.chunk_size += 1
                    pager = Pager(chunks, page_size=max(1, self.chunk_size))
                    context.say(self.current_text(pager.current()))
                    continue
                if command.name == "less":
                    self.chunk_size = max(1, self.chunk_size - 1)
                    pager = Pager(chunks, page_size=max(1, self.chunk_size))
                    context.say(self.current_text(pager.current()))
                    continue
                if command.name in {"find", "filter"} and command.argument:
                    location = self.find_chunk(command.argument)
                    if location is None:
                        context.say(f'No matches for "{command.argument}".')
                    else:
                        pager.go_to(location + 1)
                        context.say(self.current_text(pager.current()))
                    continue
            lowered = text.strip().lower()
            if lowered in {"paragraph mode", "sentence mode", "line mode"}:
                self.chunk_mode = lowered.removesuffix(" mode")
                chunks = self.make_chunks(self.chunk_mode)
                pager = Pager(chunks, page_size=max(1, self.chunk_size))
                context.say(self.current_text(pager.current()))
                continue
            if lowered in {"done", "close", ""}:
                return
            context.fail("Use reading commands like next, prev, summary, or sentence mode.")

    def make_chunks(self, mode: str) -> list[str]:
        """Break the text into meaningful chunks."""
        if mode == "line":
            return [line for line in self.text.splitlines() if line.strip()] or [self.text]
        if mode == "sentence":
            return [item.strip() for item in re.split(r"(?<=[.!?])\s+", self.text) if item.strip()] or [self.text]
        return [item.strip() for item in re.split(r"\n\s*\n", self.text) if item.strip()] or [self.text]

    def header_text(self) -> str:
        """Render the opening summary."""
        paragraphs = len(self.make_chunks("paragraph"))
        return f"{self.title}. {paragraphs} paragraphs."

    def summary_text(self) -> str:
        """Render the short summary."""
        if self.summary:
            return self.summary
        first_sentence = self.make_chunks("sentence")[0]
        return f"Summary: {first_sentence}"

    def current_text(self, page: Page[str]) -> str:
        """Render the current reader page."""
        label = (
            "Paragraph" if self.chunk_mode == "paragraph" else ("Sentence" if self.chunk_mode == "sentence" else "Line")
        )
        lines = [f"{label} {page.start_index + 1} to {page.end_index} of {page.total_items}:"]
        lines.extend(page.items)
        return "\n".join(lines)

    def find_chunk(self, query: str) -> int | None:
        """Find the first chunk containing the query."""
        normalized = normalize_text(query)
        for index, chunk in enumerate(self.make_chunks(self.chunk_mode)):
            if normalized in normalize_text(chunk):
                return index
        return None


@dataclass
class TableViewer:
    """Read a table in a row-summary-oriented way."""

    title: str
    rows: Sequence[Mapping[str, Any]]
    columns: Sequence[TableColumn] | None = None
    focus_columns: list[str] = field(default_factory=list)
    row_index: int = 0

    def run(self, context: InteractionContext) -> None:
        """Run the viewer."""
        if not self.rows:
            context.say(f"{self.title}. No rows.")
            return
        if self.columns is None:
            first_row = dict(self.rows[0])
            self.columns = [TableColumn(name=name) for name in first_row]
        context.say(f"Table: {self.title}. {len(self.rows)} rows.")
        context.say(self.render_current_row())
        while True:
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)
            if command is not None:
                if context.apply_common_command(
                    command,
                    help_text="Commands here: next, prev, row 5, columns, focus total status, find, filter, cell row 2 total.",
                    status=lambda: f"Row {self.row_index + 1} of {len(self.rows)}.",
                    summary=lambda: f"{len(self.rows)} rows.",
                    details=self.render_current_row,
                ):
                    continue
                if command.name == "next":
                    self.row_index = min(self.row_index + 1, len(self.rows) - 1)
                    context.say(self.render_current_row())
                    continue
                if command.name == "prev":
                    self.row_index = max(self.row_index - 1, 0)
                    context.say(self.render_current_row())
                    continue
                if command.name == "row" and command.argument and command.argument.isdigit():
                    self.row_index = min(max(int(command.argument) - 1, 0), len(self.rows) - 1)
                    context.say(self.render_current_row())
                    continue
                if command.name == "columns":
                    context.say("Columns: " + ", ".join(column.label or column.name for column in self.columns))
                    continue
                if command.name == "focus" and command.argument:
                    names = command.argument.split()
                    self.focus_columns = names
                    context.say("Columns in focus: " + ", ".join(names) + ".")
                    context.say(self.render_current_row())
                    continue
                if command.name == "cell" and command.argument:
                    cell_text = self.render_cell(command.argument)
                    if cell_text is None:
                        context.fail("Use cell row 2 total.")
                    else:
                        context.say(cell_text)
                    continue
                if command.name in {"find", "filter"} and command.argument:
                    filtered = self.filter_rows(command.argument)
                    context.say(f"{len(filtered)} matching rows.")
                    if filtered:
                        context.say(self.render_row_summary(filtered[0], row_number=1))
                    continue
            if text.strip().lower() in {"done", "close", ""}:
                return
            context.fail("Use table commands like next, row 5, columns, or focus status total.")

    def active_columns(self) -> list[TableColumn]:
        """Return the columns currently in focus."""
        if not self.focus_columns or self.columns is None:
            return list(self.columns or [])
        selected: list[TableColumn] = []
        for name in self.focus_columns:
            for column in self.columns:
                if column.matches(name):
                    selected.append(column)
                    break
        return selected or list(self.columns)

    def render_current_row(self) -> str:
        """Render the focused row."""
        return self.render_row_summary(self.rows[self.row_index], row_number=self.row_index + 1)

    def render_row_summary(self, row: Mapping[str, Any], *, row_number: int) -> str:
        """Render one row as a compact sentence."""
        columns = self.active_columns()
        parts = []
        for column in columns:
            value = column.render(dict(row))
            if self.focus_columns:
                parts.append(value)
            else:
                parts.append(f"{column.label or column.name} {value}")
        return f"Row {row_number}. " + ", ".join(parts) + "."

    def render_cell(self, argument: str) -> str | None:
        """Render one specific cell."""
        match = re.fullmatch(r"row\s+(\d+)\s+(.+)", argument.strip(), re.IGNORECASE)
        if match is None or self.columns is None:
            return None
        row_number = int(match.group(1))
        column_name = match.group(2).strip()
        if not (1 <= row_number <= len(self.rows)):
            return None
        row = dict(self.rows[row_number - 1])
        for column in self.columns:
            if column.matches(column_name):
                return f"Cell. Row {row_number}, {column.label or column.name}: {column.render(row)}."
        return None

    def filter_rows(self, query: str) -> list[Mapping[str, Any]]:
        """Find rows containing the given text."""
        normalized = normalize_text(query)
        result = []
        for row in self.rows:
            haystack = " ".join(str(value) for value in row.values())
            if normalized in normalize_text(haystack):
                result.append(row)
        return result


@dataclass
class SearchResultsViewer(ListViewer):
    """Named wrapper for search results."""
