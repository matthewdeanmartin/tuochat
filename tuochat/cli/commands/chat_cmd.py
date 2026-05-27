"""Automation-friendly chat commands: chat new, chat send, chat show, chat latest.

These commands form the primary non-interactive surface for LLM-driven workflows.
Every command finishes and exits (one process per turn), never requires an
interactive TTY, and produces either markdown (default) or JSON output.

JSON envelope shape:
    {
      "ok": true,
      "command": "chat new",
      "conversation": { "id": ..., "title": ..., "cwd": ..., ... },
      "result": { ... },
      "warnings": [],
      "errors": []
    }
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from tuochat.cli.command_models import ChatLatestCommand, ChatNewCommand, ChatSendCommand, ChatShowCommand
    from tuochat.config import TuochatConfig
    from tuochat.models import Conversation
    from tuochat.persistence import ConversationStore, NullConversationStore


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def conversation_envelope(conv: Conversation) -> dict[str, Any]:
    """Produce the standard conversation block for a JSON envelope."""
    return {
        "id": conv.id,
        "title": conv.title or "Untitled",
        "cwd": conv.cwd,
        "resource_id": conv.resource_id,
        "model": None,  # filled in by callers that know the active model
    }


def ok_envelope(command: str, conv: Conversation, result: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """Build a success JSON envelope."""
    env = conversation_envelope(conv)
    env["model"] = result.pop("model", None)
    return {
        "ok": True,
        "command": command,
        "conversation": env,
        "result": result,
        "warnings": warnings,
        "errors": [],
    }


def err_envelope(command: str, errors: list[str]) -> dict[str, Any]:
    """Build a failure JSON envelope."""
    return {
        "ok": False,
        "command": command,
        "conversation": None,
        "result": {},
        "warnings": [],
        "errors": errors,
    }


def print_envelope(envelope: dict[str, Any], fmt: str) -> None:
    """Print an envelope in the requested format."""
    from tuochat.serialization import json_dumps  # noqa: E402

    if fmt == "json":
        print(json_dumps(envelope, indent=True))
        return
    # markdown / plaintext — human and LLM friendly
    conv = envelope.get("conversation") or {}
    ok = envelope.get("ok", False)
    result = envelope.get("result") or {}
    errors = envelope.get("errors") or []
    warnings = envelope.get("warnings") or []
    command = envelope.get("command", "")

    lines: list[str] = []
    status = "ok" if ok else "error"
    lines.append(f"# tuochat {command} — {status}")
    if conv:
        lines.append("")
        lines.append("## Conversation")
        lines.append(f"- id: {conv.get('id', '')}")
        lines.append(f"- title: {conv.get('title', 'Untitled')}")
        if conv.get("cwd"):
            lines.append(f"- cwd: {conv['cwd']}")
        if conv.get("resource_id"):
            lines.append(f"- resource_id: {conv['resource_id']}")
        if conv.get("model"):
            lines.append(f"- model: {conv['model']}")
    if result:
        lines.append("")
        lines.append("## Result")
        response_text = result.pop("response_text", None)
        for k, v in result.items():
            if v is not None:
                lines.append(f"- {k}: {v}")
        if response_text:
            lines.append("")
            lines.append("### Response")
            lines.append(str(response_text))
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
    if errors:
        lines.append("")
        lines.append("## Errors")
        for e in errors:
            lines.append(f"- {e}")
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Conversation targeting helpers
# ---------------------------------------------------------------------------


def resolve_target_conversation(
    store: ConversationStore | NullConversationStore,
    target: str,
    resolve_conversation_id: Callable,
) -> tuple[str | None, list[str]]:
    """Resolve a conversation target string to a full conversation ID.

    Returns (conversation_id | None, warnings).
    Target may be:
      - "latest"          → most recently updated conversation
      - an ID prefix      → resolved via resolve_conversation_id
    """
    warnings: list[str] = []
    if target == "latest":
        conversations = store.list_conversations(limit=1)
        if not conversations:
            return None, warnings
        return conversations[0].id, warnings
    resolved = resolve_conversation_id(store, target)
    if resolved is None:
        return None, warnings
    return resolved, warnings


def apply_cwd_override(conv: Conversation, cwd_override: Path | None, *, restore_cwd: bool) -> list[str]:
    """Apply cwd logic and chdir if needed. Returns warnings."""
    warnings: list[str] = []
    if cwd_override is not None:
        target = cwd_override.expanduser().resolve()
        if target.is_dir():
            os.chdir(target)
            conv.cwd = str(target)
        else:
            warnings.append(f"--cwd {cwd_override!r} is not a valid directory; ignoring")
        return warnings
    if restore_cwd and conv.cwd:
        saved = Path(conv.cwd)
        if saved.is_dir():
            os.chdir(saved)
        else:
            warnings.append(f"Saved cwd {conv.cwd!r} no longer exists; staying in {os.getcwd()!r}")
    return warnings


# ---------------------------------------------------------------------------
# `chat new`
# ---------------------------------------------------------------------------


def run_chat_new(
    cfg: TuochatConfig,
    command: ChatNewCommand,
    *,
    build_provider: Callable,
    build_store: Callable,
) -> int:
    """Create a new conversation and optionally send the first message."""
    from tuochat.cli.commands.headless_cmd import (  # noqa: E402
        HeadlessInteractiveActionRequired,
        build_headless_state,
        execute_turn,
        prepare_prompt_text,
        resolve_include_paths,
        resolve_provider,
        resolve_skill_attachment,
        resolve_web_attachments,
        save_output_file,
    )
    from tuochat.cli.session import apply_git_repo_write_here_default, resolve_streaming_enabled  # noqa: E402
    from tuochat.context.composer import compose_system_prompt, load_custom_instruction_sections  # noqa: E402
    from tuochat.models import Conversation  # noqa: E402

    cmd_name = "chat new"
    warnings: list[str] = []

    try:
        has_prompt = bool(command.prompt or command.prompt_file or command.use_stdin or command.template)

        if command.cwd is not None:
            target_cwd = command.cwd.expanduser().resolve()
            if target_cwd.is_dir():
                os.chdir(target_cwd)
            else:
                warnings.append(f"--cwd {command.cwd!r} is not a valid directory; ignoring")

        provider = resolve_provider(cfg, model=command.model, timeout=command.timeout, build_provider=build_provider)
        store = build_store(cfg)
        try:
            system_prompt, prompt_sources = compose_system_prompt(
                command.system_prompt,
                load_custom_instruction_sections(cfg),
            )
            conv = Conversation(
                resource_id=command.resource_id or cfg.chat.default_resource_id,
                system_prompt=system_prompt,
                cwd=str(Path.cwd()),
            )

            if not has_prompt:
                # Create the conversation but do not send any message
                store.save_conversation(conv)
                result: dict[str, Any] = {
                    "model": command.model,
                    "response_text": None,
                    "saved_markdown_path": None,
                    "extracted_file_paths": [],
                }
                envelope = ok_envelope(cmd_name, conv, result, warnings)
                print_envelope(envelope, command.format)
                return 0

            user_input, template_metadata = prepare_prompt_text(
                command.prompt,
                command.prompt_file,
                command.use_stdin,
                command.template,
                command.variables,
                cfg,
            )
            state = build_headless_state(
                cfg,
                conversation=conv,
                store=store,
                provider=provider,
                streaming=resolve_streaming_enabled(cfg, no_stream_requested=command.no_stream),
                active_model=command.model,
                prompt_sources=prompt_sources,
                timeout_override=command.timeout,
            )
            apply_git_repo_write_here_default(cfg)
            attachments = resolve_include_paths(command.includes)
            for path, message in attachments:
                state.pending_attachment_messages.append(message)
                state.pending_attachment_names.append(str(path))
            web_attachments = resolve_web_attachments(command.web_urls, cfg)
            for url, message in web_attachments:
                state.pending_attachment_messages.append(message)
                state.pending_attachment_names.append(url)
            skill_attachment = resolve_skill_attachment(command.skill, cfg)
            if skill_attachment is not None:
                path, message = skill_attachment
                state.pending_attachment_messages.append(message)
                state.pending_attachment_names.append(str(path))
            state.pending_template_metadata = template_metadata
            execution = execute_turn(state, user_input, json_output=command.format == "json")
        finally:
            store.close()

        save_output_file(command.output_file, execution.response_text)
        result = {
            "model": execution.model,
            "response_text": execution.response_text,
            "saved_markdown_path": str(execution.markdown_path) if execution.markdown_path else None,
            "extracted_file_paths": [str(p) for p in execution.extracted_paths],
            "output_file": str(command.output_file) if command.output_file else None,
        }
        envelope = ok_envelope(cmd_name, execution.conversation, result, warnings)
        print_envelope(envelope, command.format)
        return 0

    except (HeadlessInteractiveActionRequired, OSError, RuntimeError, ValueError) as exc:
        msg = str(exc)
        print(msg, file=sys.stderr)
        if command.format == "json":
            from tuochat.serialization import json_dumps  # noqa: E402

            print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
        return 1


# ---------------------------------------------------------------------------
# `chat send`
# ---------------------------------------------------------------------------


def run_chat_send(
    cfg: TuochatConfig,
    command: ChatSendCommand,
    *,
    build_provider: Callable,
    build_store: Callable,
    resolve_conversation_id: Callable,
) -> int:
    """Send one message to an existing conversation and exit."""
    from tuochat.cli.commands.headless_cmd import (  # noqa: E402
        HeadlessInteractiveActionRequired,
        build_headless_state,
        execute_turn,
        prepare_prompt_text,
        resolve_include_paths,
        resolve_provider,
        resolve_skill_attachment,
        resolve_web_attachments,
        save_output_file,
    )
    from tuochat.cli.session import apply_git_repo_write_here_default, resolve_streaming_enabled  # noqa: E402

    cmd_name = "chat send"
    warnings: list[str] = []

    try:
        user_input, template_metadata = prepare_prompt_text(
            command.prompt,
            command.prompt_file,
            command.use_stdin,
            command.template,
            command.variables,
            cfg,
        )
        provider = resolve_provider(cfg, model=command.model, timeout=command.timeout, build_provider=build_provider)
        store = build_store(cfg)
        try:
            conversation_id, target_warnings = resolve_target_conversation(
                store, command.conversation, resolve_conversation_id
            )
            warnings.extend(target_warnings)

            if conversation_id is None:
                if command.fail_if_missing:
                    msg = f"No conversation found matching {command.conversation!r}"
                    print(msg, file=sys.stderr)
                    if command.format == "json":
                        from tuochat.serialization import json_dumps  # noqa: E402

                        print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
                    return 1
                # Fall back to creating a new conversation
                warnings.append(f"No conversation found matching {command.conversation!r}; starting a new conversation")
                from tuochat.context.composer import (  # noqa: E402
                    compose_system_prompt,
                    load_custom_instruction_sections,
                )
                from tuochat.models import Conversation  # noqa: E402

                system_prompt, prompt_sources = compose_system_prompt(None, load_custom_instruction_sections(cfg))
                conv = Conversation(
                    resource_id=cfg.chat.default_resource_id,
                    system_prompt=system_prompt,
                    cwd=str(Path.cwd()),
                )
            else:
                conv = store.get_conversation(conversation_id)
                if conv is None:
                    msg = f"Conversation {conversation_id!r} not found in store."
                    print(msg, file=sys.stderr)
                    if command.format == "json":
                        from tuochat.serialization import json_dumps  # noqa: E402

                        print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
                    return 1
                conv.messages = store.get_messages(conversation_id)
                from tuochat.context.composer import (  # noqa: E402
                    compose_system_prompt,
                    load_custom_instruction_sections,
                )

                prompt_sources = ["saved conversation prompt (embedded in transcript)"] if conv.system_prompt else []
                # Apply cwd logic
                cwd_warnings = apply_cwd_override(conv, command.cwd, restore_cwd=command.restore_cwd)
                warnings.extend(cwd_warnings)

            state = build_headless_state(
                cfg,
                conversation=conv,
                store=store,
                provider=provider,
                streaming=resolve_streaming_enabled(cfg, no_stream_requested=command.no_stream),
                active_model=command.model,
                prompt_sources=prompt_sources,
                timeout_override=command.timeout,
                resumed_context_pending=bool(conv.messages),
            )
            apply_git_repo_write_here_default(cfg)
            attachments = resolve_include_paths(command.includes)
            for path, message in attachments:
                state.pending_attachment_messages.append(message)
                state.pending_attachment_names.append(str(path))
            web_attachments = resolve_web_attachments(command.web_urls, cfg)
            for url, message in web_attachments:
                state.pending_attachment_messages.append(message)
                state.pending_attachment_names.append(url)
            skill_attachment = resolve_skill_attachment(command.skill, cfg)
            if skill_attachment is not None:
                path, message = skill_attachment
                state.pending_attachment_messages.append(message)
                state.pending_attachment_names.append(str(path))
            state.pending_template_metadata = template_metadata
            execution = execute_turn(state, user_input, json_output=command.format == "json")
        finally:
            store.close()

        save_output_file(command.output_file, execution.response_text)
        result: dict[str, Any] = {
            "model": execution.model,
            "response_text": execution.response_text,
            "saved_markdown_path": str(execution.markdown_path) if execution.markdown_path else None,
            "extracted_file_paths": [str(p) for p in execution.extracted_paths],
            "output_file": str(command.output_file) if command.output_file else None,
        }
        envelope = ok_envelope(cmd_name, execution.conversation, result, warnings)
        print_envelope(envelope, command.format)
        return 0

    except (HeadlessInteractiveActionRequired, OSError, RuntimeError, ValueError) as exc:
        msg = str(exc)
        print(msg, file=sys.stderr)
        if command.format == "json":
            from tuochat.serialization import json_dumps  # noqa: E402

            print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
        return 1


# ---------------------------------------------------------------------------
# `chat show`
# ---------------------------------------------------------------------------


def run_chat_show(
    cfg: TuochatConfig,
    command: ChatShowCommand,
    *,
    build_store: Callable,
    no_write_enabled: Callable,
    resolve_conversation_id: Callable,
) -> int:
    """Inspect conversation metadata and state."""
    from tuochat.serialization import json_dumps  # noqa: E402

    cmd_name = "chat show"
    if no_write_enabled(cfg):
        msg = "chat show is unavailable while no-write mode is enabled."
        print(msg, file=sys.stderr)
        if command.format == "json":
            print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
        return 1

    store = build_store(cfg)
    try:
        conversation_id, warnings = resolve_target_conversation(store, command.conversation, resolve_conversation_id)
        if conversation_id is None:
            if command.fail_if_missing:
                msg = f"No conversation found matching {command.conversation!r}"
                print(msg, file=sys.stderr)
                if command.format == "json":
                    print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
                return 1
            msg = f"No conversation found matching {command.conversation!r}"
            print(msg, file=sys.stderr)
            if command.format == "json":
                print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
            return 1
        conv = store.get_conversation(conversation_id)
        if conv is None:
            msg = f"Conversation {conversation_id!r} not found in store."
            print(msg, file=sys.stderr)
            if command.format == "json":
                print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
            return 1
        messages = store.get_messages(conversation_id)
    finally:
        store.close()

    result: dict[str, Any] = {
        "message_count": len(messages),
        "archived": conv.archived,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "system_prompt": conv.system_prompt,
    }

    if command.format == "json":
        env = conversation_envelope(conv)
        payload = {
            "ok": True,
            "command": cmd_name,
            "conversation": env,
            "result": result,
            "warnings": warnings,
            "errors": [],
        }
        print(json_dumps(payload, indent=True))
        return 0

    # markdown output
    lines: list[str] = [f"# tuochat {cmd_name}"]
    lines.append("")
    lines.append("## Conversation")
    lines.append(f"- id: {conv.id}")
    lines.append(f"- title: {conv.title or 'Untitled'}")
    if conv.cwd:
        lines.append(f"- cwd: {conv.cwd}")
    if conv.resource_id:
        lines.append(f"- resource_id: {conv.resource_id}")
    lines.append(f"- archived: {conv.archived}")
    lines.append(f"- created_at: {conv.created_at}")
    lines.append(f"- updated_at: {conv.updated_at}")
    lines.append(f"- message_count: {len(messages)}")
    if conv.system_prompt:
        lines.append("")
        lines.append("## System Prompt")
        lines.append(conv.system_prompt)
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# `chat latest`
# ---------------------------------------------------------------------------


def run_chat_latest(
    cfg: TuochatConfig,
    command: ChatLatestCommand,
    *,
    build_store: Callable,
    no_write_enabled: Callable,
) -> int:
    """Show the most recent active conversation."""
    from tuochat.serialization import json_dumps  # noqa: E402

    cmd_name = "chat latest"
    if no_write_enabled(cfg):
        msg = "chat latest is unavailable while no-write mode is enabled."
        print(msg, file=sys.stderr)
        if command.format == "json":
            print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
        return 1

    store = build_store(cfg)
    try:
        conversations = store.list_conversations(limit=1)
    finally:
        store.close()

    if not conversations:
        msg = "No conversations found."
        if command.format == "json":
            print(json_dumps(err_envelope(cmd_name, [msg]), indent=True))
        else:
            print(msg)
        return 0

    conv = conversations[0]

    if command.format == "json":
        payload = {
            "ok": True,
            "command": cmd_name,
            "conversation": conversation_envelope(conv),
            "result": {
                "archived": conv.archived,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at,
            },
            "warnings": [],
            "errors": [],
        }
        print(json_dumps(payload, indent=True))
        return 0

    # markdown output
    lines: list[str] = [f"# tuochat {cmd_name}"]
    lines.append("")
    lines.append("## Latest Conversation")
    lines.append(f"- id: {conv.id}")
    lines.append(f"- title: {conv.title or 'Untitled'}")
    if conv.cwd:
        lines.append(f"- cwd: {conv.cwd}")
    if conv.resource_id:
        lines.append(f"- resource_id: {conv.resource_id}")
    lines.append(f"- updated_at: {conv.updated_at}")
    print("\n".join(lines))
    return 0
