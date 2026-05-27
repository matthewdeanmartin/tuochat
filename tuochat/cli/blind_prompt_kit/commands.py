"""Global command parsing for blind-first prompts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """Parsed command."""

    name: str
    argument: str | None = None
    raw: str = ""

    def matches(self, *names: str) -> bool:
        """Return whether the command name matches one of the provided names."""
        return self.name in names


command_aliases = {
    "?": "help",
    "help": "help",
    "repeat": "repeat",
    "back": "back",
    "skip": "skip",
    "cancel": "cancel",
    "done": "done",
    "status": "status",
    "more": "more",
    "less": "less",
    "brief": "brief",
    "verbose": "verbose",
    "show": "show",
    "summary": "summary",
    "details": "details",
    "list": "list",
    "next": "next",
    "prev": "prev",
    "previous": "prev",
    "first": "first",
    "last": "last",
    "clear": "clear",
    "edit": "edit",
    "count": "count",
    "columns": "columns",
    "path": "path",
    "full": "full",
}

commands_with_arguments = {
    "show",
    "edit",
    "pick",
    "find",
    "filter",
    "match",
    "change",
    "remove",
    "open",
    "page",
    "jump",
    "item",
    "details",
    "focus",
    "sort",
    "row",
    "cell",
    "field",
    "refine",
    "mode",
}


def parse_command(text: str) -> Command | None:
    """Parse a raw command if the text looks like one."""
    stripped = text.strip()
    if not stripped:
        return None
    parts = stripped.split(maxsplit=1)
    verb = command_aliases.get(parts[0].lower())
    if verb is None:
        if parts[0].lower() in commands_with_arguments and len(parts) > 1:
            return Command(parts[0].lower(), parts[1].strip(), raw=text)
        return None
    argument = parts[1].strip() if len(parts) > 1 else None
    if verb not in commands_with_arguments and argument is not None:
        return None
    return Command(verb, argument, raw=text)


def parse_literal_text(text: str) -> str | None:
    """Return a literal text value when the input explicitly escapes command parsing."""
    if text.startswith("\\") and len(text) > 1:
        return text[1:]
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() in {"literal", "text"}:
        return parts[1]
    return None


def parse_yes_no(text: str) -> bool | None:
    """Parse a boolean answer."""
    normalized = text.strip().lower()
    if normalized in {"y", "yes", "true", "confirm"}:
        return True
    if normalized in {"n", "no", "false"}:
        return False
    return None
