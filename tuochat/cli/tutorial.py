"""Built-in tutorial flow for the interactive CLI."""

# ruff: noqa: E402,F401,F403,F811,F821,B010
from __future__ import annotations

import logging
import sys

from tuochat.cli.io import get_backend
from tuochat.cli.models import ReplState
from tuochat.cli.prompts import prompt_input, read_user_message, submit_key_hint
from tuochat.cli.rendering import announce_screen_transition, clear_screen
from tuochat.cli.session import no_write_enabled
from tuochat.constants import (
    TUTORIAL_CONTINUE_CHOICES,
    TUTORIAL_LESSON_ORDER,
    TUTORIAL_LESSONS,
    TUTORIAL_PICKER_ALIASES,
)

logger = logging.getLogger("tuochat.cli")


def tutorial_lesson_aliases() -> dict[str, str]:
    """Return aliases that resolve to tutorial lesson ids."""
    aliases: dict[str, str] = {}
    for lesson_id in TUTORIAL_LESSON_ORDER:
        data = TUTORIAL_LESSONS[lesson_id]
        title = str(data["title"]).lower()
        aliases[lesson_id] = lesson_id
        aliases[lesson_id.replace("-", "")] = lesson_id
        aliases[title] = lesson_id
        aliases[title.replace(" ", "-")] = lesson_id
        aliases[title.replace(" ", "")] = lesson_id
    return aliases


def prompt_tutorial_continue() -> bool:
    """Ask whether to continue to the next lesson."""
    choice = prompt_input("Continue tutorial? [Y/n] ").strip().lower()
    return choice in TUTORIAL_CONTINUE_CHOICES


def run_multiline_tutorial_practice() -> None:
    """Let the user practice multiline submission before moving on."""
    backend = get_backend()
    while True:
        print()
        if backend.supports_multiline:
            print("Practice now: type a message (Enter adds lines), then press Alt+S to submit.")
            print("On Windows you can also use Ctrl+Z to submit a non-empty buffer.")
        else:
            print("Practice now: enter at least one line, then submit it with the normal EOF key.")
            if sys.platform == "win32":
                print("On Windows that means Ctrl+Z, then Enter.")
            else:
                print("On macOS and Linux that means Ctrl+D.")
        practiced, should_exit = read_user_message(quiet=True)
        if should_exit or not practiced or not practiced.strip():
            print("No practice text received yet. Please try once so you can feel the submit flow.")
            continue
        print()
        print("Captured practice input:")
        print(practiced)
        return


def run_eliza_tutorial_practice() -> None:
    """Let the user exchange a message with Eliza inside the tutorial."""
    from tuochat.provider.eliza import ElizaProvider

    eliza = ElizaProvider()
    backend = get_backend()
    print()
    print("Eliza is a simple pattern-matching bot — not Duo, not AI.")
    print("She is here so you can try the interface without any network connection.")
    print()

    if backend.supports_multiline:
        print("Type a greeting below and press Alt+S (or Ctrl+Z on Windows) to send it.")
    else:
        hint = submit_key_hint()
        print(f"Type a greeting below and press {hint} to send it.")

    message, should_exit = read_user_message(quiet=True)
    if should_exit or not message or not message.strip():
        print("(No input — skipping Eliza exchange.)")
        return

    print()
    print("Eliza> ", end="", flush=True)
    for chunk in eliza.chat(message.strip(), streaming=True):
        print(chunk, end="", flush=True)
    print()
    print()
    print("That was Eliza. When you are ready, switch to Duo with `/model duo`.")


def print_tutorial_picker() -> None:
    """Show numbered tutorial lessons."""
    print("Tutorial lessons:")
    for index, lesson_id in enumerate(TUTORIAL_LESSON_ORDER, start=1):
        lesson = TUTORIAL_LESSONS[lesson_id]
        print(f"  [{index}] {lesson['title']}: {lesson['summary']}")


def resolve_tutorial_lesson(argument: str) -> str | None:
    """Resolve a lesson name or number."""
    raw = argument.strip().lower()
    if not raw:
        return TUTORIAL_LESSON_ORDER[0]
    if raw in TUTORIAL_PICKER_ALIASES:
        return "__pick__"
    if raw.isdigit():
        index = int(raw) - 1
        if 0 <= index < len(TUTORIAL_LESSON_ORDER):
            return TUTORIAL_LESSON_ORDER[index]
        return None
    return tutorial_lesson_aliases().get(raw)


def print_tutorial_lesson(lesson_id: str, *, lesson_number: int, lesson_total: int) -> None:
    """Clear the screen and print one tutorial lesson."""
    lesson = TUTORIAL_LESSONS[lesson_id]
    body = lesson.get("body")
    if not isinstance(body, list):
        return
    clear_screen()
    print(f"Tutorial {lesson_number}/{lesson_total}: {lesson['title']}")
    print()
    for line in body:
        print(line)


def persist_tutorial_completed(state: ReplState) -> None:
    """Persist tutorial completion when local writes are allowed."""
    from tuochat.config import save_config

    state.cfg.chat.tutorial_completed = True
    if no_write_enabled(state.cfg):
        return
    required_root_attrs = (
        "setup_version",
        "gitlab",
        "notifications",
        "personalization",
        "classification",
        "warn_words",
        "config_dir",
        "log_dir",
    )
    required_chat_attrs = (
        "platform_origin",
        "default_resource_id",
        "timeout",
        "websocket_welcome_timeout",
        "websocket_subscription_timeout",
        "streaming",
        "mask_output",
        "dot_timer",
        "quiet",
        "no_banner",
        "response_footer_warning_enabled",
        "response_footer_warning_text",
        "generated_file_header_enabled",
        "generated_file_header_text",
        "max_request_chars",
        "context_window_tokens",
        "conversation_expiration_days",
        "no_write",
        "tutorial_completed",
        "safety_check_extension_for_executable_files",
    )
    if not all(hasattr(state.cfg, attr) for attr in required_root_attrs):
        return
    if not all(hasattr(state.cfg.chat, attr) for attr in required_chat_attrs):
        return
    save_config(state.cfg, state.config_path)


def run_tutorial(state: ReplState, argument: str = "") -> None:
    """Run the built-in tutorial."""
    selection = resolve_tutorial_lesson(argument)
    if selection is None:
        print("Usage: /tutorial [lesson-name|number|pick]", file=sys.stderr)
        return
    if selection == "__pick__":
        print_tutorial_picker()
        picked = prompt_input("tutorial> ").strip()
        if not picked:
            print("Tutorial selection cancelled.")
            return
        selection = resolve_tutorial_lesson(picked)
        if selection in {None, "__pick__"}:
            print("Unknown tutorial lesson.", file=sys.stderr)
            return
    if selection is None:
        return

    persist_tutorial_completed(state)
    start_index = TUTORIAL_LESSON_ORDER.index(selection)
    remaining = TUTORIAL_LESSON_ORDER[start_index:]
    total = len(remaining)
    for offset, lesson_id in enumerate(remaining, start=1):
        print_tutorial_lesson(lesson_id, lesson_number=offset, lesson_total=total)
        if lesson_id == "multiline-input":
            run_multiline_tutorial_practice()
        elif lesson_id == "eliza-demo":
            run_eliza_tutorial_practice()
        if offset != total and not prompt_tutorial_continue():
            print("Tutorial paused. Resume any time with `/tutorial` or `/tutorial pick`.")
            return

    print()
    print("Tutorial complete. Re-run it any time with `/tutorial`.")
    prompt_input("[done, hit any key] ")
    if state.blind_mode:
        announce_screen_transition("Classification")
    else:
        clear_screen()


__all__ = [
    "tutorial_lesson_aliases",
    "prompt_tutorial_continue",
    "run_multiline_tutorial_practice",
    "run_eliza_tutorial_practice",
    "print_tutorial_picker",
    "resolve_tutorial_lesson",
    "print_tutorial_lesson",
    "persist_tutorial_completed",
    "run_tutorial",
]
