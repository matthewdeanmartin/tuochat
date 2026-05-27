"""CLI integration: detect sandbox-eligible code blocks, prompt, execute, queue output."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tuochat.cli.io import read_prompt
from tuochat.patterns import FENCED_BLOCK_RE
from tuochat.sandbox.api import resolve_language, run_code
from tuochat.sandbox.protocol import CodeInput, CodeOutput

if TYPE_CHECKING:
    from tuochat.context.attachments import AttachmentState

logger = logging.getLogger(__name__)


def extract_sandbox_block(response: str) -> tuple[str, str] | None:
    """Find the first fenced code block with a sandbox-eligible language tag.

    Returns (language, code) or None.
    """
    for match in FENCED_BLOCK_RE.finditer(response):
        info = match.group(1).strip()
        language = resolve_language(info)
        if language is not None:
            return language, match.group(2)
    return None


def prompt_execute(language: str) -> bool:
    """Ask the user whether to execute the detected code block."""
    try:
        answer = read_prompt(f"  Execute {language} code in sandbox? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def prompt_attach() -> bool:
    """Ask the user whether to attach sandbox output to the conversation."""
    try:
        answer = read_prompt("  Attach output to conversation? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer not in ("n", "no")


def format_sandbox_output(output: CodeOutput) -> str:
    """Format a CodeOutput as an attachment message."""
    lines = ["Sandbox execution result:"]
    if output.stdout:
        lines.append("")
        lines.append("stdout:")
        lines.append("```")
        lines.extend(output.stdout)
        lines.append("```")
    if output.ok:
        lines.append("")
        lines.append(f"Result: {format_result(output.result)}")
    else:
        lines.append("")
        error = output.error or {}
        lines.append(f"Error ({error.get('type', 'Unknown')}): {error.get('message', 'unknown error')}")
    if output.metrics:
        wall = output.metrics.get("wall_ms")
        if wall is not None:
            lines.append(f"Wall time: {wall:.1f}ms")
    return "\n".join(lines)


def format_result(value: Any) -> str:
    """Format a result value for display."""
    import json

    if value is None:
        return "(no value emitted)"
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def handle_sandbox_response(
    response: str,
    state: AttachmentState,
) -> bool:
    """Check a response for sandbox blocks, prompt, execute, and optionally queue output.

    Returns True if a block was executed.
    """
    block = extract_sandbox_block(response)
    if block is None:
        return False

    language, code = block
    print(f"\n  Detected {language} code block.")

    if not prompt_execute(language):
        print("  Skipped.")
        return False

    request = CodeInput(code=code, language=language)
    print("  Running...", end="", flush=True)
    output = run_code(request)

    if output.ok:
        print(" done.")
    else:
        print(" failed.")

    # Show output immediately
    formatted = format_sandbox_output(output)
    print()
    print(formatted)

    # Offer to attach
    if prompt_attach():
        from tuochat.context.attachments import queue_attachment

        attachment_msg = f"Path: [sandbox]\n```text\n{formatted}\n```"
        queue_attachment(state, Path("[sandbox]"), attachment_msg)
        print("  Output queued as attachment for next message.")

    return True
