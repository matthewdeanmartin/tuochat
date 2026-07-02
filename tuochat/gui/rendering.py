"""Pure rendering helpers, formatters, and constants for the Tkinter GUI.

These functions produce text or data and have no dependency on Tk widgets.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tuochat.__about__ import __description__, __license__, __title__, __version__
from tuochat.cli.io import redirect_standard_io
from tuochat.cli.models import ReplState
from tuochat.cli.rendering import humanize_report_key, print_context
from tuochat.cli.repl import print_help, print_help_menu, print_help_section, resolve_help_topic, week_start_iso
from tuochat.cli.setup import get_valid_classifications
from tuochat.config import TuochatConfig
from tuochat.constants import MODEL_LABELS, classification_definition, classification_help_label
from tuochat.context.composer import ATTACHED_CODE_PROMPT
from tuochat.discovery.agent_prompts import auto_select_agent_prompt
from tuochat.estimation import estimate_token_cost, format_cost, format_quantity
from tuochat.models import Conversation, ConversationSearchResult, Message

export_filename_pattern = re.compile(r"[^A-Za-z0-9._ -]+")


def humanize_date(iso_str: str | None) -> str:
    """Return a human-friendly relative date string like '2 hours ago'."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "just now"
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes}m ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        if seconds < 7 * 86400:
            days = seconds // 86400
            return f"{days}d ago"
        if seconds < 30 * 86400:
            weeks = seconds // (7 * 86400)
            return f"{weeks}w ago"
        if seconds < 365 * 86400:
            months = seconds // (30 * 86400)
            return f"{months}mo ago"
        years = seconds // (365 * 86400)
        return f"{years}y ago"
    except (ValueError, TypeError):
        return iso_str[:19] if iso_str else ""


# bg, fg, input_bg, input_fg, select_bg
THEME_COLORS: dict[str, tuple[str, str, str, str, str]] = {
    "light": ("#ffffff", "#000000", "#f0f8ff", "#000000", "#0078d7"),
    "dark": ("#1e1e1e", "#d4d4d4", "#2d2d2d", "#d4d4d4", "#264f78"),
    "green_terminal": ("#0d1a0d", "#00cc44", "#0a1408", "#00cc44", "#004d1a"),
    "amber_terminal": ("#1a1200", "#ffaa00", "#150e00", "#ffaa00", "#4d3300"),
    "solarized": ("#002b36", "#839496", "#073642", "#839496", "#268bd2"),
    "hot_dog_stand": ("#ff0000", "#ffff00", "#cc0000", "#ffff00", "#ff6600"),
}


def theme_colors(theme: str) -> tuple[str, str, str, str, str] | None:
    """Return (bg, fg, input_bg, input_fg, select_bg) for a named theme, or None for system."""
    return THEME_COLORS.get(theme)


def conversation_menu_label(conv: Conversation, *, current_id: str | None = None) -> str:
    """Return a compact label for a recent conversation menu item."""
    title = (conv.title or "Untitled")[:40]
    updated = humanize_date(conv.updated_at)
    current_marker = "* " if current_id and conv.id == current_id else ""
    return f"{current_marker}{title}  {updated}".rstrip()


def default_export_filename(conv: Conversation) -> str:
    """Return a safe default markdown filename for a conversation export."""
    base_name = (conv.title or conv.id[:8] or "conversation").strip()
    cleaned = export_filename_pattern.sub("-", base_name).strip(" .-_")
    if not cleaned:
        cleaned = "conversation"
    return f"{cleaned}.md"


def render_conversation_markdown(conv: Conversation, messages: list[Message] | None = None) -> str:
    """Render a conversation to markdown using in-memory state."""
    rendered_messages = messages if messages is not None else list(conv.messages)
    lines = [f"# {conv.title or 'Untitled Conversation'}", ""]
    if conv.system_prompt:
        lines.extend([f"**System prompt:** {conv.system_prompt}", ""])
    lines.append(f"*Started: {conv.created_at}*")
    lines.append("")

    for msg in rendered_messages:
        role_label = msg.role.capitalize()
        lines.append(f"## {role_label}")
        lines.append("")
        lines.append(msg.content)
        lines.append("")

    return "\n".join(lines)


def confirm_nuke(
    *,
    ask_yes_no,
    ask_text,
) -> bool:
    """Return whether the caller confirmed the destructive nuke action."""
    confirmed = ask_yes_no(
        "Confirm nuke",
        "Delete centralized app data and close tuochat?\n\nThis keeps the config folder and current workspace.",
    )
    if not confirmed:
        return False
    typed = ask_text("Confirm nuke", "Type `nuke` to confirm data deletion:")
    return typed is not None and typed.strip().lower() == "nuke"


def is_classification_prompt(prompt: str) -> bool:
    """Return whether a prompt is the CLI classification picker."""
    return prompt.strip().lower().startswith("classify")


def classification_dialog_text(
    cfg: TuochatConfig,
    *,
    current: str | None = None,
    upcoming: bool = False,
) -> str:
    """Build the GUI classification chooser body text."""
    options = get_valid_classifications(cfg)
    label = "the upcoming conversation" if upcoming else "this conversation"
    lines = [
        f"Document classification for {label}.",
        "Enter a picker number or the exact classification text.",
        "",
    ]
    for index, option in enumerate(options, start=1):
        marker = " * current" if option == current else ""
        lines.append(f"[{index}] {classification_help_label(option)}{marker}")
    return "\n".join(lines)


def format_token_usage(input_tokens: int, output_tokens: int) -> str:
    """Render the current session token totals in a compact human-friendly form."""
    total_tokens = input_tokens + output_tokens
    return f"Token usage: in {input_tokens:,} | out {output_tokens:,} | total {total_tokens:,}"


def format_info_line(
    *,
    input_tokens: int,
    output_tokens: int,
    active_model: str,
    working_directory: Path,
    classification: str | None,
    elapsed_seconds: float | None,
    sandbox_runtime_summary: str | None = None,
) -> str:
    """Render the compact first-row session summary."""
    definition = classification_definition(classification)
    classification_label = definition.full_name if definition is not None else (classification or "(none)")
    parts: list[str] = []
    if elapsed_seconds is not None:
        parts.append(f"Elapsed: {elapsed_seconds:.2f}s")
    parts.extend(
        [
            format_token_usage(input_tokens, output_tokens),
            f"Model: {MODEL_LABELS.get(active_model, active_model)}",
            f"Cwd: {working_directory}",
            f"Classification: {classification_label}",
        ]
    )
    if sandbox_runtime_summary:
        parts.append(f"Sandbox: {sandbox_runtime_summary}")
    return " | ".join(parts)


def format_writing_directory_line(writing_directory: str) -> str:
    """Render the dedicated second-row writing-directory label."""
    return f"Writing dir: {writing_directory}"


def format_sandbox_runtime_summary(runtime_details: dict[str, object]) -> str:
    """Render a compact sandbox-runtime summary for the GUI info bar."""
    mini_racer_v8 = "yes" if runtime_details.get("mini_racer_v8") else "no"
    lupa = "yes" if runtime_details.get("lupa") else "no"
    return f"mini-racer/V8 {mini_racer_v8} | lupa {lupa}"


def response_warning_text(cfg: TuochatConfig) -> str:
    """Return the compact response warning text when enabled."""
    if not cfg.chat.response_footer_warning_enabled:
        return ""
    return cfg.chat.response_footer_warning_text.strip()


def configured_gui_model(cfg: TuochatConfig) -> str | None:
    """Choose the initial GUI provider from the usable configuration."""
    if cfg.gitlab.host and cfg.gitlab.token:
        return "duo"
    if cfg.openrouter.api_key and cfg.openrouter.effective_models():
        return "openrouter"
    return None


def next_model_key(active_model: str) -> str:
    """Return the next provider key in the GUI model cycle."""
    model_keys = tuple(MODEL_LABELS)
    try:
        current_index = model_keys.index(active_model)
    except ValueError:
        return model_keys[0]
    return model_keys[(current_index + 1) % len(model_keys)]


def next_model_toggle_label(active_model: str) -> str:
    """Return the toolbar label for cycling to the next provider."""
    next_model = next_model_key(active_model)
    return f"Use {MODEL_LABELS[next_model]}"


def attachment_speedbar_labels() -> tuple[str, ...]:
    """Return the compact attachment-control labels for the main speedbar."""
    return (
        "Attach",
        "Files",
        "Folder",
        "Skills",
        "Initial Instr",
        "Template",
        "Changed",
        "Detach All",
        "Agent Prompt",
    )


def about_dialog_text() -> str:
    """Build the About dialog text shown by the GUI."""
    app_name = __title__.title()
    lines = [
        app_name,
        f"Version: {__version__}",
        "Author: Matthew Dean Martin",
        "",
        __description__,
        f"License: {__license__}",
        "",
        "Tuochat is about 99% written by ChatGPT, Codex, Copilot, Gemini, Claude Code.",
        "As such, the copyrightability of the code is indeterimined and if the law says it is not",
        "copyrightable, then the code is Public Domain. Anything that is not public domain is MIT.",
        "",
        "GitLab is a trademark of GitLab.",
        "ChatGPT is a trademark of OpenAI.",
        "Claude Code is a trademark of Anthropic.",
        "Tuochat is not endorsed or related to GitLab, OpenAI, Anthropic, or any person or organization.",
    ]
    return "\n".join(lines)


MIT_LICENSE_TEXT = """\
MIT License

Copyright (c) 2024 Matthew Dean Martin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def keyboard_shortcuts_text() -> str:
    """Return the keyboard shortcuts reference shown in the Help menu dialog."""
    lines = [
        "Keyboard Shortcuts",
        "==================",
        "",
        "Submitting messages",
        "  Alt+S           Send the current draft",
        "",
        "Navigation",
        "  Alt+H           Show the Help tab",
        "  Alt+T           Run /status (show session status)",
        "  Alt+Q           Quit tuochat",
        "",
        "Input history",
        "  Up arrow        Previous prompt from history",
        "  Down arrow      Next prompt (or restore draft)",
        "",
        "Text editing (standard Tkinter text widget bindings)",
        "  Ctrl+Z          Undo",
        "  Ctrl+Shift+Z    Redo  (or Ctrl+Y on Windows)",
        "  Ctrl+A          Select all (in focused widget)",
        "  Ctrl+C          Copy selection",
        "  Ctrl+X          Cut selection",
        "  Ctrl+V          Paste",
        "  Home / End      Start / end of line",
        "  Ctrl+Home       Start of document",
        "  Ctrl+End        End of document",
    ]
    return "\n".join(lines)


def window_title_text(title: str | None) -> str:
    """Return the application window title for the active conversation."""
    cleaned = (title or "").strip()
    return f"Tuochat: {cleaned}" if cleaned else "Tuochat"


def render_attached_files_text(state: ReplState) -> str:
    """Render the Files tab from the current attachment-related session state."""
    from tuochat.estimation import estimate_tokens

    names = state.pending_attachment_names or []
    messages = state.pending_attachment_messages or []
    lines: list[str] = []

    # Agent prompt section
    if state.include_agents_file:
        if state.active_agent_prompt_path:
            lines.append(f"Agent prompt: {state.active_agent_prompt_path.name} ({state.active_agent_prompt_mode})")
        else:
            lines.append(f"Agent prompt: auto ({state.active_agent_prompt_mode})")
    else:
        lines.append("Agent prompt: excluded")

    if state.pending_custom_name:
        lines.append(f"Pending custom instructions for next new conversation: {state.pending_custom_name}")
    lines.append("")

    if names:
        lines.append(f"Pending attachments ({len(names)}):")
        for index, name in enumerate(names, start=1):
            kind_hint = ""
            if name.startswith("[skill]"):
                kind_hint = "skill"
            elif name.startswith("[template]"):
                kind_hint = "template"
            elif name.startswith("[recipe]"):
                kind_hint = "recipe"
            elif name.startswith("[custom_instruction]"):
                kind_hint = "custom instruction"
            token_hint = ""
            if index - 1 < len(messages):
                tokens = estimate_tokens(messages[index - 1])
                token_hint = f"  (~{tokens:,} tokens)"
            kind_prefix = f"  [{kind_hint}]  " if kind_hint else "  "
            lines.append(f"[{index}]{kind_prefix}{name}{token_hint}")
    else:
        lines.append("No attachments are currently queued.")

    if state.last_include_path is not None:
        lines.extend(
            [
                "",
                f"Last include: {state.last_include_path}",
                f"Last include size: {(state.last_include_size or 0):,} bytes",
            ]
        )
    return "\n".join(lines)


def attached_files_dialog_text(paths: list[Path]) -> str:
    """Build the post-selection attachment summary text."""
    lines = [
        "Attached these files for the next request.",
        "",
    ]
    for index, path in enumerate(paths, start=1):
        lines.append(f"[{index}] {path}")
    return "\n".join(lines)


def is_attached_code_prompt(prompt: str) -> bool:
    """Return whether a prompt should use the template code-file picker."""
    normalized = prompt.strip().rstrip(":>").strip().casefold()
    expected = ATTACHED_CODE_PROMPT.strip().rstrip(":>").strip().casefold()
    return normalized == expected


def render_context_text(state: ReplState) -> str:
    """Render the effective context snapshot for the Context tab."""
    from tuochat.workspace_memory import load_pinned_sections

    buffer = io.StringIO()
    with redirect_standard_io(stdout=buffer, stderr=buffer):  # type: ignore[arg-type]
        print_context(state)
    rendered = buffer.getvalue().strip()

    # Effective agent prompt section
    agent_lines: list[str] = []
    if state.include_agents_file:
        active_path = state.active_agent_prompt_path
        if active_path is None:
            auto_path, _ = auto_select_agent_prompt()
            active_path = auto_path
        if active_path and active_path.is_file():
            agent_lines.append(f"Active agent prompt: {active_path.name}  ({active_path})")
            agent_lines.append(f"Mode: {state.active_agent_prompt_mode}")
        else:
            agent_lines.append("Active agent prompt: (none found in cwd)")
    else:
        agent_lines.append("Active agent prompt: excluded")

    # Workspace pinned memory files
    pinned = load_pinned_sections()
    pinned_lines: list[str] = []
    if pinned:
        pinned_lines.append("Workspace pinned (injected into every conversation system prompt):")
        for label, content in pinned:
            preview = content[:120].replace("\n", " ")
            if len(content) > 120:
                preview += "..."
            pinned_lines.append(f"  {label}: {preview}")
    else:
        pinned_lines.append("Workspace pinned: (none — use /memory, /todo, /compact to create)")

    if state.server_context:
        server_lines = ["Server context items:"]
        for index, item in enumerate(state.server_context, start=1):
            server_lines.append(f"[{index}] {item['category']} - {item['name']}")
        rendered = f"{rendered}\n\n" + "\n".join(server_lines) if rendered else "\n".join(server_lines)

    agent_section = "\n".join(agent_lines)
    pinned_section = "\n".join(pinned_lines)
    header = f"{agent_section}\n\n{pinned_section}"
    if rendered:
        return f"{header}\n\n{rendered}"
    return header


def render_conversations_text(
    conversations: list[Conversation],
    *,
    current_id: str | None = None,
    unavailable: bool = False,
) -> str:
    """Render the Conversations tab from recent saved conversations."""
    if unavailable:
        return "Saved conversations are unavailable while no-write mode is enabled."
    if not conversations:
        return "No saved conversations yet."

    lines = ["Recent conversations (read-only for now):"]
    for index, conv in enumerate(conversations, start=1):
        lines.append(f"[{index}] {conversation_menu_label(conv, current_id=current_id)}")
    return "\n".join(lines)


def render_search_results_text(
    search_results: list[ConversationSearchResult] | None,
    *,
    query: str | None = None,
) -> str:
    """Render the Search tab from the latest conversation search results."""
    if not search_results:
        if query:
            return f"No saved conversations matched {query!r}."
        return "No search results yet. Run /search to populate this tab."

    lines = [f"Search results for {query!r}:" if query else "Search results:"]
    for index, match in enumerate(search_results, start=1):
        title = (match.title or "Untitled")[:40]
        updated = match.updated_at[:19] if match.updated_at else ""
        role = match.role[:9]
        snippet = re.sub(r"\s+", " ", (match.snippet or "").strip()) or "(no snippet)"
        lines.append(f"[{index}] {match.conversation_id[:8]}  {title}  {updated}  {role}")
        lines.append(f"    {snippet}")
    return "\n".join(lines)


def render_wire_transcript_text(state: ReplState) -> str:
    """Render the exact bytes going over the wire for the Transcript tab.

    Shows each completed turn as [USER] / [ASSISTANT] blocks containing the
    full outbound payload (attachments + prompt) and the full response.
    Appends a [PENDING — not yet sent] block when there are queued attachments
    or a pending turn ready to go.
    """
    from tuochat.models import Role

    lines: list[str] = []

    separator = "=" * 72

    # --- Completed turns stored in the conversation ---
    for msg in state.conv.messages:
        if msg.role == Role.USER.value:
            lines.append(separator)
            ts = msg.created_at[:19] if msg.created_at else ""
            lines.append(f"[USER]  {ts}")
            lines.append(separator)
            lines.append(msg.content)
            lines.append("")
        elif msg.role == Role.ASSISTANT.value:
            lines.append(separator)
            ts = msg.created_at[:19] if msg.created_at else ""
            lines.append(f"[ASSISTANT]  {ts}")
            lines.append(separator)
            lines.append(msg.content)
            lines.append("")

    # --- Pending attachments (scheduled to send with next request) ---
    pending_names = state.pending_attachment_names or []
    pending_messages = state.pending_attachment_messages or []
    if pending_names or pending_messages:
        # Build a read-only preview without mutating state.resumed_context_pending.
        header = "These files are related to the upcoming request:\n"
        if pending_names:
            header += "\n".join(f"- {name}" for name in pending_names)
            header += "\n\n"
        preview = header + "\n\n".join(pending_messages) + "\n\nUpcoming request:\n<next user message>"
        lines.append(separator)
        lines.append("[PENDING — attached, not yet sent]")
        lines.append(separator)
        lines.append(preview)
        lines.append("")

    if not lines:
        return "No messages yet. Start a conversation to see the wire transcript."

    return "\n".join(lines)


def render_help_text(command_text: str, *, blind_mode: bool = False) -> str:
    """Render /help output into a text block for the Help tab."""
    stripped = command_text.strip() or "/help"
    command, _, argument = stripped.partition(" ")
    normalized_command = command.lower()
    normalized_argument = argument.strip()
    buffer = io.StringIO()

    with redirect_standard_io(stdout=buffer, stderr=buffer):  # type: ignore[arg-type]
        if normalized_command == "/help-menu":
            print_help_menu()
        elif normalized_command == "/help":
            topic = resolve_help_topic(normalized_argument)
            if topic == "menu":
                print_help_menu()
            elif topic is not None:
                print_help_section(topic)
            elif normalized_argument:
                print("Usage: /help [menu|session|files|history|output|safety|exit]")
            elif blind_mode:
                print_help_menu()
            else:
                print_help()
        else:
            print_help()

    return buffer.getvalue().strip() or "Help is unavailable."


def render_weekly_usage_text(store: Any) -> str:
    """Render the weekly usage summary for the Usage tab."""
    week_start = week_start_iso()
    totals = store.get_weekly_usage(week_start)
    input_tok = totals["input_tokens"]
    output_tok = totals["output_tokens"]
    total_tok = totals["total_tokens"]
    turns = totals["turns"]
    input_cost, output_cost, total_cost = estimate_token_cost(input_tok, output_tok)
    approx_words = int(total_tok / 1.3)
    approx_chars = total_tok * 4
    approx_kb = approx_chars / 1024
    rows = [
        ("turns", format_quantity(turns)),
        ("input_tokens", format_quantity(input_tok)),
        ("output_tokens", format_quantity(output_tok)),
        ("total_tokens", format_quantity(total_tok)),
        ("approximate_words", format_quantity(approx_words)),
        ("approximate_characters", format_quantity(approx_chars)),
        ("approximate_kilobytes", format_quantity(approx_kb, decimals=1)),
        ("input_cost", format_cost(input_cost)),
        ("output_cost", format_cost(output_cost)),
        ("total_cost", format_cost(total_cost)),
    ]
    lines = [f"Weekly usage (since {week_start[:10]}, resets Sunday):"]
    lines.extend(f"{humanize_report_key(key)}: {value}" for key, value in rows)
    return "\n".join(lines)


def submit_shortcut_sequences() -> tuple[str, ...]:
    """Return key bindings that submit the current draft."""
    return ("<Alt-s>", "<Alt-S>")
