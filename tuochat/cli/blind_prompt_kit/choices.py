"""Choice and multi-select components."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .core import InteractionContext
from .matching import normalize_text, rank_choices
from .models import Choice
from .pagination import Pager

ValueT = TypeVar("ValueT")


def make_status_snapshot(
    component: ChoiceInput[ValueT],
    filtered: list[Choice[ValueT] | Choice[str]],
    pager: Pager[Choice[ValueT] | Choice[str]],
) -> callable:
    """Bind the current filtered list and pager for command help callbacks."""
    def status_snapshot() -> str:
        return component.status_text(filtered, pager)

    return status_snapshot


def make_details_snapshot(
    component: ChoiceInput[ValueT],
    pager: Pager[Choice[ValueT] | Choice[str]],
) -> callable:
    """Bind the current pager for command detail callbacks."""
    def details_snapshot() -> str:
        return component.page_text(pager.current())

    return details_snapshot


def coerce_choices(options: Sequence[Choice[ValueT] | str]) -> list[Choice[ValueT] | Choice[str]]:
    """Normalize raw strings into Choice objects."""
    result: list[Choice[ValueT] | Choice[str]] = []
    for option in options:
        if isinstance(option, Choice):
            result.append(option)
        else:
            result.append(Choice(label=option, value=option))
    return result


def default_page_size(item_count: int) -> int:
    """Return the suggested page size."""
    if item_count <= 9:
        return max(1, item_count)
    if item_count <= 25:
        return 7
    return 5


@dataclass
class ChoiceInput(Generic[ValueT]):
    """Pick one choice from a list."""

    prompt: str
    options: Sequence[Choice[ValueT] | str]
    default: ValueT | None = None
    help_text: str | None = None
    page_size: int | None = None
    choices: list[Choice[ValueT] | Choice[str]] = field(init=False)

    def __post_init__(self) -> None:
        """Prepare normalized choices."""
        self.choices = coerce_choices(self.options)

    def run(self, context: InteractionContext) -> ValueT | str:
        """Run the picker."""
        if not self.choices:
            raise ValueError("ChoiceInput requires at least one option.")
        page_size = self.page_size or default_page_size(len(self.choices))
        filtered = list(self.choices)
        pager = Pager(filtered, page_size=page_size)
        self.announce_start(context)
        while True:
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)

            status_snapshot = make_status_snapshot(self, filtered, pager)
            details_snapshot = make_details_snapshot(self, pager)

            if command is not None:
                if context.apply_common_command(
                    command,
                    help_text=self.help(),
                    status=status_snapshot,
                    summary=status_snapshot,
                    details=details_snapshot,
                ):
                    continue
                if command.name == "list":
                    context.say(self.page_text(pager.current()))
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
                if command.name == "page" and command.argument and command.argument.isdigit():
                    context.say(self.page_text(pager.go_to(int(command.argument))))
                    continue
                if command.name in {"find", "filter", "match"} and command.argument:
                    filtered = self.apply_filter(command.argument)
                    pager = Pager(filtered, page_size=pager.page_size)
                    context.say(self.filtered_text(command.argument, pager))
                    continue
                if command.name == "pick" and command.argument:
                    selection = self.select_by_token(command.argument, filtered, pager.current().items)
                    if selection is not None:
                        context.say(f"{selection.display_text()} selected.")
                        return selection.value
                    context.fail("Pick a listed number or name.")
                    continue
            if not text.strip():
                if self.default is not None:
                    return self.default
                context.fail("Pick a number or name.")
                continue
            selection = self.select_by_token(text, filtered, pager.current().items)
            if selection is not None:
                context.say(f"{selection.display_text()} selected.")
                return selection.value
            matches = self.apply_filter(text)
            if not matches:
                context.fail(f'No matches for "{text.strip()}". Type a new filter, say list, or back.')
                continue
            if len(matches) == 1:
                only = matches[0]
                if normalize_text(text) == normalize_text(only.label):
                    context.say(f"{only.display_text()} selected.")
                    return only.value
                if context.ask_yes_no(f"One match: {only.display_text()}. Select it?", default=True):
                    context.say(f"{only.display_text()} selected.")
                    return only.value
                continue
            filtered = matches
            pager = Pager(filtered, page_size=pager.page_size)
            context.say(self.filtered_text(text, pager))

    def announce_start(self, context: InteractionContext) -> None:
        """Speak the initial prompt."""
        count = len(self.choices)
        if count <= 9:
            context.say(f"{self.prompt} {count} options.")
            context.say(self.page_text(Pager(self.choices, page_size=count).current()))
            context.say("Pick by number or name.")
            return
        if count <= 25:
            context.say(f"{self.prompt} {count} options. Type to match, or say list.")
            return
        context.say(f"{self.prompt} {count} options. Type part of the name.")

    def help(self) -> str:
        """Render step-local help."""
        return self.help_text or "Type a number or name. Commands here: list, next, prev, find, pick, more, less, back."

    def apply_filter(self, query: str) -> list[Choice[ValueT] | Choice[str]]:
        """Filter the available choices."""
        return list(rank_choices(query, self.choices))

    def select_by_token(
        self,
        token: str,
        filtered: Sequence[Choice[ValueT] | Choice[str]],
        visible: Sequence[Choice[ValueT] | Choice[str]],
    ) -> Choice[ValueT] | Choice[str] | None:
        """Resolve a selection token."""
        stripped = token.strip()
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(visible):
                return visible[index]
            return None
        matches = rank_choices(stripped, filtered)
        if len(matches) == 1 and normalize_text(matches[0].label) == normalize_text(stripped):
            return matches[0]
        if len(matches) == 1 and normalize_text(matches[0].display_text()) == normalize_text(stripped):
            return matches[0]
        return None

    def status_text(
        self, filtered: Sequence[Choice[ValueT] | Choice[str]], pager: Pager[Choice[ValueT] | Choice[str]]
    ) -> str:
        """Summarize the current picker state."""
        page = pager.current()
        return f"{len(filtered)} available. Showing {page.start_index + 1} to {page.end_index}."

    def filtered_text(self, query: str, pager: Pager[Choice[ValueT] | Choice[str]]) -> str:
        """Render the current filtered view."""
        count = len(pager.items)
        if count == 0:
            return f'No matches for "{query}".'
        page = pager.current()
        lines = [f"{count} matches."]
        lines.append(self.page_text(page))
        return "\n".join(lines)

    def page_text(self, page) -> str:
        """Render one page of choices."""
        if not page.items:
            return "No items."
        lines: list[str] = []
        if page.total_items > len(page.items):
            lines.append(f"Items {page.start_index + 1} to {page.end_index} of {page.total_items}.")
        for index, item in enumerate(page.items, start=1):
            line = f"{index}. {item.display_text()}"
            if item.description:
                line = f"{line} - {item.description}"
            lines.append(line)
        if page.total_items > len(page.items):
            lines.append("Say next, prev, pick 3, or type a match.")
        return "\n".join(lines)


@dataclass
class EnumInput(ChoiceInput[ValueT]):
    """Choice input that exposes help text from item descriptions."""

    def help(self) -> str:
        """Render descriptive option help."""
        descriptions = [f"{choice.label} means {choice.description}." for choice in self.choices if choice.description]
        if not descriptions:
            return super().help()
        return "\n".join(descriptions + ["Pick by number or name."])


@dataclass
class MultiSelectInput(Generic[ValueT]):
    """Pick zero or more items from a list."""

    prompt: str
    options: Sequence[Choice[ValueT] | str]
    required: bool = False
    help_text: str | None = None
    page_size: int | None = None
    choices: list[Choice[ValueT] | Choice[str]] = field(init=False)

    def __post_init__(self) -> None:
        """Prepare normalized choices."""
        self.choices = coerce_choices(self.options)

    def run(self, context: InteractionContext) -> list[ValueT | str]:
        """Run the multi-select prompt."""
        if not self.choices:
            return []
        page_size = self.page_size or default_page_size(len(self.choices))
        filtered = list(self.choices)
        pager = Pager(filtered, page_size=page_size)
        selected: list[Choice[ValueT] | Choice[str]] = []
        context.say(f"{self.prompt} {len(self.choices)} options.")
        context.say("Pick items one at a time. Say done when finished.")
        while True:
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)

            def details_snapshot(pager_snapshot=pager) -> str:
                return self.page_text(pager_snapshot.current())

            if command is not None:
                if context.apply_common_command(
                    command,
                    help_text=self.help_text or "Commands here: list, next, prev, remove, status, clear, done.",
                    status=lambda: self.selected_text(selected),
                    summary=lambda: self.selected_text(selected),
                    details=details_snapshot,
                ):
                    continue
                if command.name == "done":
                    if selected or not self.required:
                        context.say(self.selected_text(selected))
                        return [choice.value for choice in selected]
                    context.fail("Pick at least one item before finishing.")
                    continue
                if command.name == "list":
                    context.say(self.page_text(pager.current()))
                    continue
                if command.name == "next":
                    context.say(self.page_text(pager.next()))
                    continue
                if command.name == "prev":
                    context.say(self.page_text(pager.prev()))
                    continue
                if command.name == "clear":
                    selected.clear()
                    context.say("Selections cleared.")
                    continue
                if command.name == "remove" and command.argument:
                    removed = self.remove_selection(command.argument, selected)
                    if removed is None:
                        context.fail("Select a chosen item to remove.")
                    else:
                        context.say(f"{removed.display_text()} removed. {len(selected)} selected.")
                    continue
                if command.name in {"find", "filter", "match"} and command.argument:
                    filtered = list(rank_choices(command.argument, self.choices))
                    pager = Pager(filtered, page_size=pager.page_size)
                    context.say(
                        self.page_text(pager.current()) if filtered else f'No matches for "{command.argument}".'
                    )
                    continue
            matches = rank_choices(text, filtered)
            if text.strip().isdigit():
                index = int(text.strip()) - 1
                page_items = pager.current().items
                if not (0 <= index < len(page_items)):  # pylint: disable=superfluous-parens
                    context.fail("Pick a listed number or name.")
                    continue
                choice = page_items[index]
            elif len(matches) == 1:
                choice = matches[0]
            elif len(matches) > 1:
                filtered = list(matches)
                pager = Pager(filtered, page_size=pager.page_size)
                context.say(f"{len(matches)} matches.")
                context.say(self.page_text(pager.current()))
                continue
            else:
                context.fail("Pick a listed number or name.")
                continue
            if any(normalize_text(existing.label) == normalize_text(choice.label) for existing in selected):
                context.say(f"{choice.display_text()} already selected.")
                continue
            selected.append(choice)
            context.say(f"{choice.display_text()} added. {len(selected)} selected.")

    def remove_selection(
        self,
        token: str,
        selected: list[Choice[ValueT] | Choice[str]],
    ) -> Choice[ValueT] | Choice[str] | None:
        """Remove a selected item by number or name."""
        stripped = token.strip()
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(selected):
                return selected.pop(index)
            return None
        matches = rank_choices(stripped, selected)
        if len(matches) != 1:
            return None
        match = matches[0]
        selected.remove(match)
        return match

    def page_text(self, page) -> str:
        """Render one page of options."""
        if not page.items:
            return "No items."
        lines: list[str] = []
        if page.total_items > len(page.items):
            lines.append(f"Items {page.start_index + 1} to {page.end_index} of {page.total_items}.")
        for index, item in enumerate(page.items, start=1):
            lines.append(f"{index}. {item.display_text()}")
        return "\n".join(lines)

    def selected_text(self, selected: Sequence[Choice[ValueT] | Choice[str]]) -> str:
        """Render the selection summary."""
        if not selected:
            return "No items selected."
        labels = ", ".join(choice.display_text() for choice in selected)
        return f"Selected: {labels}."
