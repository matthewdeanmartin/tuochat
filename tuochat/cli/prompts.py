"""Prompt and input helpers for the interactive CLI."""

# ruff: noqa: E402,F401,F403,F811,F821,B010
from __future__ import annotations

import logging
import sys

from tuochat.cli.io import WINDOWS_INLINE_EOF_CHAR, get_backend, read_prompt

logger = logging.getLogger("tuochat.cli")

MESSAGE_CANCELLED_HINT = "Message cancelled. Use /quit or /exit to exit."


def prompt_nonempty(prompt: str, *, default: str | None = None, secret: bool = False) -> str:
    """Prompt until a non-empty value is entered."""
    while True:
        if secret:
            value = read_prompt(prompt, secret=True)
        else:
            value = prompt_input(prompt)
        trimmed = value.strip()
        if trimmed:
            return trimmed
        if default is not None:
            return default
        print("A value is required.", file=sys.stderr)


def prompt_text(prompt: str, *, default: str | None = None, secret: bool = False) -> str:
    """Prompt for optional text, returning the default on blank input."""
    while True:
        value = read_prompt(prompt, secret=True) if secret else prompt_input(prompt)
        trimmed = value.strip()
        if trimmed:
            return trimmed
        if default is not None:
            return default
        return ""


def readprompt_input(prompt: str) -> tuple[str, bool]:
    """Read one prompt line, treating EOF submit keys as a blank response."""
    try:
        value = read_prompt(prompt)
    except EOFError:
        print()
        return "", True
    value, saw_inline_eof, had_trailing_text = split_inline_eof_marker(value)
    if saw_inline_eof:
        if had_trailing_text:
            print("\n[Warning: stripped text that appeared after Ctrl+Z.]", file=sys.stderr)
        print()
        return value, True
    return value, False


def prompt_input(prompt: str) -> str:
    """Read one prompt line while allowing Ctrl+Z/Ctrl+D as submit/blank input."""
    value, _submitted = readprompt_input(prompt)
    return value


def prompt_bool(prompt: str, *, default: bool) -> bool:
    """Prompt for a yes/no value with a default."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        choice = prompt_input(f"{prompt} {suffix} ").strip().lower()
        if not choice:
            return default
        if choice in {"y", "yes"}:
            return True
        if choice in {"n", "no"}:
            return False
        print("Please answer y or n.", file=sys.stderr)


def prompt_int(prompt: str, *, default: int, minimum: int = 0) -> int:
    """Prompt for an integer value with validation."""
    while True:
        raw = prompt_input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and int(raw) >= minimum:
            return int(raw)
        print(f"Enter an integer >= {minimum}.", file=sys.stderr)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return values with duplicates removed while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def prompt_csv_list(prompt: str, *, default: list[str] | None = None) -> list[str]:
    """Prompt for a comma-separated list."""
    default = default or []
    default_label = ", ".join(default)
    raw = prompt_input(f"{prompt} [{default_label}]: ").strip()
    if not raw:
        return list(default)
    return dedupe_preserve_order([item for item in (part.strip() for part in raw.split(",")) if item])


def prompt_pick_many(label: str, options: list[str], *, default: list[str] | None = None) -> list[str]:
    """Prompt for one or more numbered options."""
    default = list(default or [])
    print(label)
    for idx, option in enumerate(options, start=1):
        print(f"  [{idx}] {option}")
    default_label = ", ".join(default) if default else "none"
    print("Type numbers separated by commas, or `all`.")
    while True:
        raw = prompt_input(f"Selection [{default_label}]: ").strip()
        if not raw:
            return default
        if raw.lower() == "all":
            return ["All"] if options and options[0] == "All" else list(options)
        chosen: list[str] = []
        ok = True
        for part in raw.split(","):
            token = part.strip()
            if not token.isdigit():
                ok = False
                break
            index = int(token) - 1
            if index < 0 or index >= len(options):
                ok = False
                break
            chosen.append(options[index])
        if ok:
            chosen = dedupe_preserve_order(chosen)
            if "All" in chosen:
                return ["All"]
            return chosen
        print("Use one or more numbers from the list, or `all`.", file=sys.stderr)


def submit_key_hint() -> str:
    """Return the platform-appropriate EOF submission hint."""
    if sys.platform == "win32":
        return "Ctrl+Z, Enter"
    return "Ctrl+D"


def split_inline_eof_marker(line: str) -> tuple[str, bool, bool]:
    """Strip an inline Windows EOF marker from input() results.

    On Windows, ``input()`` may return ``WINDOWS_INLINE_EOF_CHAR`` (``\\x1a``)
    as a literal character when Ctrl+Z is pressed at the end of a non-empty
    line instead of raising EOFError immediately. Treat that character as the
    end-of-input marker so slash commands and pasted content are submitted
    consistently.
    """
    if WINDOWS_INLINE_EOF_CHAR not in line:
        return line, False, False
    content, _marker, rest = line.partition(WINDOWS_INLINE_EOF_CHAR)
    return content, True, bool(rest)


def read_user_message(*, quiet: bool = False) -> tuple[str | None, bool]:
    """Read a multiline user message terminated by EOF.

    Returns (message, should_exit). If EOF is received before any content,
    should_exit is True so the REPL can terminate cleanly. Ctrl+C cancels the
    current draft and returns control to the prompt without sending anything.

    When the active backend supports native multiline editing (e.g.
    prompt-toolkit), the full draft is collected in a single editor session
    rather than the line-by-line loop used by the readline/input() backend.
    """
    from tuochat.cli.io import prompt_handler_var

    backend = get_backend()
    if backend.supports_multiline and prompt_handler_var.get() is None and sys.stdin.isatty():
        return read_user_message_multiline(quiet=quiet)
    return read_user_message_linewise(quiet=quiet)


def read_user_message_multiline(*, quiet: bool = False) -> tuple[str | None, bool]:
    """Collect a full multiline draft via the prompt-toolkit backend."""
    backend = get_backend()
    prompt = "you> " if quiet else "you (Alt+S to submit)>\n"
    try:
        text = backend.read_multiline(prompt)  # type: ignore[attr-defined]
    except KeyboardInterrupt:
        print()
        print(MESSAGE_CANCELLED_HINT, file=sys.stderr)
        return None, False
    except EOFError:
        print()
        return None, True
    text = text.strip()
    if not text:
        return None, True
    return text, False


def read_user_message_linewise(*, quiet: bool = False) -> tuple[str | None, bool]:
    """Collect a multiline message one line at a time, terminated by EOF."""
    lines: list[str] = []
    prompt_hint = submit_key_hint()
    while True:
        try:
            if quiet:
                prompt = "you> " if not lines else "> "
            else:
                prompt = f"you ({prompt_hint} to submit)> " if not lines else "... "
            line = read_prompt(prompt)
        except KeyboardInterrupt:
            print()
            print(MESSAGE_CANCELLED_HINT, file=sys.stderr)
            return None, False
        except EOFError:
            print()
            if not lines:
                return None, True
            return "\n".join(lines), False
        line, saw_inline_eof, had_trailing_text = split_inline_eof_marker(line)
        if saw_inline_eof:
            if had_trailing_text:
                print("\n[Warning: stripped text that appeared after Ctrl+Z.]", file=sys.stderr)
            print()
            if line:
                lines.append(line)
            if not lines:
                return None, True
            return "\n".join(lines), False
        lines.append(line)


def prompt_missing_slash_command(command_name: str) -> bool | None:
    """Ask whether to execute a bare command name as a slash command."""
    while True:
        choice = (
            prompt_input(f"Input matches '/{command_name}'. Execute slash command or send as prompt? [E/s] ")
            .strip()
            .lower()
        )
        if choice in {"", "e", "execute"}:
            return True
        if choice in {"s", "send", "prompt"}:
            return False
        if choice in {"c", "cancel"}:
            return None
        print("Please choose E to execute or S to send.", file=sys.stderr)


__all__ = [
    "prompt_nonempty",
    "prompt_text",
    "readprompt_input",
    "prompt_input",
    "prompt_bool",
    "prompt_int",
    "dedupe_preserve_order",
    "prompt_csv_list",
    "prompt_pick_many",
    "submit_key_hint",
    "split_inline_eof_marker",
    "MESSAGE_CANCELLED_HINT",
    "read_user_message",
    "prompt_missing_slash_command",
]
