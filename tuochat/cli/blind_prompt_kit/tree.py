"""Tree and file navigation components."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from .core import InteractionContext
from .exceptions import StepBack
from .matching import normalize_text
from .models import FilePick, TreeNode

ValueT = TypeVar("ValueT")


def make_node_snapshot(
    navigator: TreeNavigator[ValueT],
    stack_snapshot: list[TreeNode[ValueT]],
) -> callable:
    """Bind a tree stack snapshot for help callbacks."""
    def describe_snapshot() -> str:
        return navigator.describe_node(stack_snapshot)

    return describe_snapshot


@dataclass
class TreeNavigator(Generic[ValueT]):
    """Navigate a simple tree."""

    root: TreeNode[ValueT]
    prompt: str = "Tree"

    def run(self, context: InteractionContext) -> TreeNode[ValueT] | None:
        """Navigate the tree and optionally pick a node."""
        stack: list[TreeNode[ValueT]] = [self.root]
        while True:
            current = stack[-1]
            context.say(self.describe_node(stack))
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)
            if command is not None:
                snapshot = list(stack)

                describe_snapshot = make_node_snapshot(self, snapshot)

                try:
                    if context.apply_common_command(
                        command,
                        help_text="Commands here: open 1, pick 1, back, path, list.",
                        status=describe_snapshot,
                        summary=describe_snapshot,
                        details=describe_snapshot,
                    ):
                        continue
                except StepBack:
                    if len(stack) == 1:
                        context.fail("Already at the root.")
                    else:
                        stack.pop()
                    continue
                if command.name == "path":
                    context.say("Path: " + " > ".join(node.label for node in stack))
                    continue
                if command.name == "list":
                    context.say(self.describe_node(stack))
                    continue
                if command.name == "open" and command.argument:
                    child = self.pick_child(current.children, command.argument)
                    if child is None:
                        context.fail("Pick a listed child.")
                    elif child.children:
                        stack.append(child)
                    else:
                        context.say(f"{child.label} has no children.")
                    continue
                if command.name == "pick" and command.argument:
                    child = self.pick_child(current.children, command.argument)
                    if child is None:
                        context.fail("Pick a listed child.")
                    else:
                        context.say(f"{child.label} selected.")
                        return child
                    continue
            if text.strip().lower() in {"done", "close", ""}:
                return None
            child = self.pick_child(current.children, text)
            if child is None:
                context.fail("Use open or pick with a listed item.")
            elif child.children:
                stack.append(child)
            else:
                context.say(f"{child.label} selected.")
                return child

    def pick_child(self, children: Sequence[TreeNode[ValueT]], token: str) -> TreeNode[ValueT] | None:
        """Pick a child by number or name."""
        stripped = token.strip()
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(children):
                return children[index]
            return None
        normalized = normalize_text(stripped)
        for child in children:
            if normalize_text(child.label) == normalized:
                return child
        return None

    def describe_node(self, stack: Sequence[TreeNode[ValueT]]) -> str:
        """Describe the current node and its immediate children."""
        current = stack[-1]
        lines = [f"Path: {' > '.join(node.label for node in stack)}"]
        lines.append(f"{len(current.children)} items.")
        for index, child in enumerate(current.children, start=1):
            lines.append(f"{index}. {child.label}")
        return "\n".join(lines)


@dataclass
class FilePicker:
    """Pick a file by traversing directories."""

    root: Path
    prompt: str = "File picker"
    include_directories: bool = False

    def run(self, context: InteractionContext) -> FilePick | None:
        """Run the file picker."""
        current = self.root.resolve()
        while True:
            entries = sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
            context.say(self.describe_directory(current, entries))
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)

            def status_snapshot(current_snapshot=current) -> str:
                return str(current_snapshot)

            def details_snapshot(current_snapshot=current, entries_snapshot=entries) -> str:
                return self.describe_directory(current_snapshot, entries_snapshot)

            if command is not None:
                try:
                    if context.apply_common_command(
                        command,
                        help_text="Commands here: open 1, pick 1, back, list.",
                        status=status_snapshot,
                        summary=status_snapshot,
                        details=details_snapshot,
                    ):
                        continue
                except StepBack:
                    if current == self.root.resolve():
                        context.fail("Already at the root.")
                    else:
                        current = current.parent
                    continue
                if command.name == "list":
                    context.say(self.describe_directory(current, entries))
                    continue
                if command.name == "open" and command.argument:
                    target = self.pick_entry(entries, command.argument)
                    if target is None or not target.is_dir():
                        context.fail("Pick a listed directory to open.")
                    else:
                        current = target
                    continue
                if command.name == "pick" and command.argument:
                    target = self.pick_entry(entries, command.argument)
                    if target is None:
                        context.fail("Pick a listed file.")
                    elif target.is_dir() and not self.include_directories:
                        context.fail("Pick a file, not a directory.")
                    else:
                        context.say(f"{target.name} selected.")
                        return FilePick(target)
                    continue
            lowered = text.strip().lower()
            if lowered in {"done", "close", ""}:
                return None
            if lowered == "back":
                if current == self.root.resolve():
                    context.fail("Already at the root.")
                else:
                    current = current.parent
                continue
            target = self.pick_entry(entries, text)
            if target is None:
                context.fail("Use open or pick with a listed item.")
            elif target.is_dir():
                current = target
            elif self.include_directories or target.is_file():
                context.say(f"{target.name} selected.")
                return FilePick(target)

    def pick_entry(self, entries: Sequence[Path], token: str) -> Path | None:
        """Pick an entry by number or name."""
        stripped = token.strip()
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(entries):
                return entries[index]
            return None
        normalized = normalize_text(stripped)
        for entry in entries:
            if normalize_text(entry.name) == normalized:
                return entry
        return None

    def describe_directory(self, directory: Path, entries: Sequence[Path]) -> str:
        """Describe the current directory."""
        lines = [f"{self.prompt}. Path: {directory}"]
        if not entries:
            lines.append("No items.")
            return "\n".join(lines)
        lines.append(f"{len(entries)} items.")
        for index, entry in enumerate(entries, start=1):
            suffix = " folder" if entry.is_dir() else ""
            lines.append(f"{index}. {entry.name}{suffix}")
        return "\n".join(lines)
