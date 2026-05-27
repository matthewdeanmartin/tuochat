"""Headless non-interactive chat commands."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tuochat.cli.models import ReplState
from tuochat.cli.pickers import resolve_skill_path, resolve_template_path
from tuochat.cli.session import (
    apply_git_repo_write_here_default,
    build_outbound_input,
    resolve_streaming_enabled,
    sync_conversation_artifacts,
    update_saved_conversation_artifacts,
)
from tuochat.context.attachments import format_included_file, read_include_file
from tuochat.context.composer import compose_system_prompt, load_custom_instruction_sections, resolve_template_prompt
from tuochat.context.validation import validate_user_request
from tuochat.discovery.skills import list_available_skills, render_skill_message
from tuochat.discovery.templates import (
    describe_template_path,
    list_available_templates,
    parse_template_metadata,
    template_body,
)
from tuochat.estimation import estimate_tokens
from tuochat.models import Conversation, MessageStatus, Role, Usage
from tuochat.observability import ObservabilityRow
from tuochat.observability import ms_between as obs_ms_between
from tuochat.observability import utc_now_iso
from tuochat.provider.duo import DuoProvider
from tuochat.provider.eliza import ElizaProvider
from tuochat.provider.openrouter import OpenRouterAPIError, OpenRouterProvider, OpenRouterUnavailableError
from tuochat.serialization import json_dumps

if TYPE_CHECKING:
    from collections.abc import Callable

    from tuochat.cli.command_models import HeadlessAskCommand, HeadlessContinueCommand
    from tuochat.config import TuochatConfig
    from tuochat.persistence import ConversationStore, NullConversationStore


ONGOING_CONVERSATION_ID = "ongoing"


class HeadlessInteractiveActionRequired(RuntimeError):
    """Raised when headless execution would require an interactive prompt."""


@dataclass
class HeadlessExecution:
    """Structured result for headless commands."""

    conversation: Conversation
    response_text: str
    model: str
    input_tokens: int
    output_tokens: int
    markdown_path: Path | None
    extracted_paths: list[Path]


def reject_interactive_prompt(prompt: str) -> str:
    """Fail fast when a non-interactive run would need user confirmation."""
    raise HeadlessInteractiveActionRequired(prompt)


def parse_variable_args(raw_values: tuple[str, ...]) -> dict[str, str]:
    """Parse repeated NAME=value template arguments."""
    values: dict[str, str] = {}
    for item in raw_values:
        if "=" not in item:
            raise ValueError(f"Expected NAME=value for --var, got: {item}")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Expected NAME=value for --var, got: {item}")
        values[name] = value
    return values


def read_prompt_source(prompt: str | None, prompt_file: Path | None, use_stdin: bool) -> str:
    """Read prompt text from a positional arg, file, or stdin."""
    sources = int(bool(prompt)) + int(prompt_file is not None) + int(use_stdin)
    if sources > 1:
        raise ValueError("Use only one of prompt text, --file, or --stdin.")
    if prompt_file is not None:
        return prompt_file.expanduser().read_text(encoding="utf-8")
    if use_stdin:
        return sys.stdin.read()
    return prompt or ""


def resolve_web_attachments(urls: tuple[str, ...], cfg: TuochatConfig) -> list[tuple[str, str]]:
    """Fetch web URLs and return (url, attachment_text) pairs.

    Skips URLs silently with a warning if web_attach is disabled.
    Raises ValueError for fetch errors so the caller can propagate to stderr.
    """
    from tuochat.web.attach import WebAttachError, fetch_and_render  # noqa: E402

    results: list[tuple[str, str]] = []
    web_cfg = cfg.web_attach
    if not web_cfg.enabled:
        if urls:
            raise ValueError("Web attachments are disabled (web_attach.enabled = false in config).")
        return results

    for url in urls:
        try:
            web_attachment = fetch_and_render(url, web_cfg)
        except WebAttachError as exc:
            raise ValueError(f"Web fetch failed for {url!r}: {exc}") from exc
        results.append((url, web_attachment.attachment_text))
    return results


def resolve_include_paths(paths: tuple[Path, ...]) -> list[tuple[Path, str]]:
    """Load include files for the next request."""
    attachments: list[tuple[Path, str]] = []
    for raw_path in paths:
        path = raw_path.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        text, _fingerprint, _size = read_include_file(path)
        attachments.append((path, format_included_file(path, text)))
    return attachments


def resolve_skill_attachment(skill: str | None, cfg: TuochatConfig) -> tuple[Path, str] | None:
    """Resolve a skill selection to a message attachment."""
    if not skill:
        return None
    candidates = list_available_skills(cfg)
    skill_path = resolve_skill_path(skill, cfg=cfg, candidates=candidates)
    if skill_path is None or not skill_path.is_file():
        raise ValueError(f"Skill file not found: {skill}")
    _label, payload = render_skill_message(skill_path, cfg)
    return skill_path, payload


def resolve_selected_template_prompt(
    template: str | None, variables: tuple[str, ...], cfg: TuochatConfig
) -> tuple[str, dict[str, object]] | None:
    """Resolve and fill a template into prompt text and stored metadata."""
    if not template:
        return None
    candidates = list_available_templates(cfg)
    template_path = resolve_template_path(template, cfg=cfg, candidates=candidates)
    if template_path is None or not template_path.is_file():
        raise ValueError(f"Template file not found: {template}")
    body = template_body(template_path)
    if not body:
        raise ValueError(f"Template file is empty: {template_path}")
    values = parse_variable_args(variables)
    rendered_prompt, template_values = resolve_template_prompt(body, provided_values=values, cwd=Path.cwd())
    metadata: dict[str, object] = {
        "path": str(template_path),
        "label": describe_template_path(template_path, cfg),
        "name": parse_template_metadata(template_path)[0],
        **template_values,
    }
    return rendered_prompt, metadata


def prepare_prompt_text(
    prompt: str | None,
    prompt_file: Path | None,
    use_stdin: bool,
    template: str | None,
    variables: tuple[str, ...],
    cfg: TuochatConfig,
) -> tuple[str, dict[str, object] | None]:
    """Build the final prompt text and optional template metadata."""
    prompt_text = read_prompt_source(prompt, prompt_file, use_stdin).strip()
    template_result = resolve_selected_template_prompt(template, variables, cfg)
    if template_result is None:
        if not prompt_text:
            raise ValueError("Provide a prompt, --file, --stdin, or --template.")
        return prompt_text, None
    template_text, metadata = template_result
    final_parts = [part for part in (template_text.strip(), prompt_text) if part]
    return "\n\n".join(final_parts), metadata


def build_headless_state(
    cfg: TuochatConfig,
    *,
    conversation: Conversation,
    store: ConversationStore | NullConversationStore,
    provider: DuoProvider | ElizaProvider | OpenRouterProvider,
    streaming: bool,
    active_model: str,
    prompt_sources: list[str],
    timeout_override: int | None = None,
    resumed_context_pending: bool = False,
) -> ReplState:
    """Create a minimal REPL state for non-interactive execution."""
    return ReplState(
        conv=conversation,
        store=store,
        provider=provider,
        cfg=cfg,
        streaming=streaming,
        timeout_override=timeout_override,
        quiet=True,
        no_banner=True,
        blind_mode=False,
        debug=False,
        base_system_prompt=conversation.system_prompt,
        base_resource_id=conversation.resource_id,
        pending_attachment_messages=[],
        pending_attachment_names=[],
        active_system_prompt_sources=prompt_sources,
        pending_template_metadata=None,
        mask_output=False,
        dot_timer_enabled=False,
        no_code_mode=False,
        active_model=active_model,
        command_log=[],
        resumed_context_pending=resumed_context_pending,
        local_writes_enabled=not cfg.chat.no_write,
    )


def is_ongoing_conversation_id(value: str) -> bool:
    """Return whether the headless target refers to the server-side ongoing Duo thread."""
    return value.strip().casefold() == ONGOING_CONVERSATION_ID


def load_or_create_ongoing_conversation(
    cfg: TuochatConfig,
    store: ConversationStore | NullConversationStore,
) -> tuple[Conversation, list[str]]:
    """Load the reserved ongoing conversation or create it on first use.

    The ongoing target is intended for Duo's ambient server-side continuity, so
    callers should avoid replaying local transcript history when using it.
    """
    conversation = store.get_conversation(ONGOING_CONVERSATION_ID)
    if conversation is None:
        system_prompt, prompt_sources = compose_system_prompt(
            None,
            load_custom_instruction_sections(cfg, mode="headless"),
        )
        conversation = Conversation(
            id=ONGOING_CONVERSATION_ID,
            resource_id=cfg.chat.default_resource_id,
            system_prompt=system_prompt,
            cwd=str(Path.cwd()),
        )
        return conversation, prompt_sources

    conversation.messages = store.get_messages(ONGOING_CONVERSATION_ID)
    prompt_sources = ["saved ongoing conversation prompt"] if conversation.system_prompt else []
    return conversation, prompt_sources


def resolve_provider(
    cfg: TuochatConfig,
    *,
    model: str,
    timeout: int | None,
    build_provider: Callable[[TuochatConfig, int | None], DuoProvider],
) -> DuoProvider | ElizaProvider | OpenRouterProvider:
    """Create the requested provider."""
    if model == "eliza":
        return ElizaProvider()
    if model == "openrouter":
        from tuochat.cli.session import build_openrouter_provider  # noqa: PLC0415

        try:
            return build_openrouter_provider(cfg)
        except (OpenRouterAPIError, OpenRouterUnavailableError) as exc:
            raise ValueError(str(exc)) from exc
    if not cfg.gitlab.host or not cfg.gitlab.token:
        raise ValueError("GitLab host and token must be configured for Duo headless mode.")
    return build_provider(cfg, timeout)


def save_output_file(output_file: Path | None, response_text: str) -> None:
    """Write the model response to a requested output file."""
    if output_file is None:
        return
    path = output_file.expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response_text, encoding="utf-8")


def persist_turn(
    state: ReplState,
    *,
    user_input: str,
    outbound_input: str,
    full_response: str,
    interrupted: bool,
) -> HeadlessExecution:
    """Persist a completed turn and return the machine-readable result."""
    input_tokens = estimate_tokens(outbound_input)
    output_tokens = estimate_tokens(full_response)
    message_extras_json = None
    if state.pending_template_metadata is not None:
        message_extras_json = json_dumps({"template": state.pending_template_metadata}, ensure_ascii=True)
    user_message = state.conv.add_message(Role.USER.value, outbound_input, extras_json=message_extras_json)
    assistant_message = state.conv.add_message(
        Role.ASSISTANT.value,
        full_response,
        status=MessageStatus.PARTIAL.value if interrupted else MessageStatus.COMPLETE.value,
    )
    if state.conv.title is None:
        state.conv.title = state.conv.auto_title(user_input)
    state.store.save_conversation(state.conv)
    state.store.save_message(user_message)
    state.store.save_message(assistant_message)
    state.store.save_usage(
        Usage(
            conversation_id=state.conv.id,
            message_id=assistant_message.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=(
                "eliza"
                if state.active_model == "eliza"
                else (
                    getattr(state.provider, "last_model_used", None) or "openrouter"
                    if state.active_model == "openrouter"
                    else "estimated"
                )
            ),
        )
    )
    archive_dir, markdown_path, extracted = sync_conversation_artifacts(
        state.cfg,
        state.conv,
        approve_write=(
            reject_interactive_prompt if state.cfg.chat.approve_writes and state.cfg.chat.write_here_mode else None
        ),
    )
    if markdown_path is not None:
        update_saved_conversation_artifacts(state, markdown_path, extracted)
    _ = archive_dir
    return HeadlessExecution(
        conversation=state.conv,
        response_text=full_response,
        model=state.active_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        markdown_path=markdown_path,
        extracted_paths=extracted,
    )


def execute_turn(state: ReplState, user_input: str, *, json_output: bool) -> HeadlessExecution:
    """Run one non-interactive turn."""
    outbound_input = build_outbound_input(state, user_input)
    try:
        valid = validate_user_request(
            user_input,
            outbound_input,
            state.cfg.chat.max_request_chars,
            state.cfg,
            reject_interactive_prompt,
            non_interactive=True,
        )
    except HeadlessInteractiveActionRequired as exc:
        raise HeadlessInteractiveActionRequired(
            f"Headless mode would require an interactive confirmation: {exc}"
        ) from exc
    if not valid:
        raise RuntimeError("Request cancelled.")

    started_at = time.perf_counter()
    request_started_at_iso = utc_now_iso()
    first_token_at_iso: str | None = None
    interrupted = False
    chunks: list[str] = []
    should_stream_stdout = state.streaming and not json_output
    if state.active_model == "eliza":
        provider = ElizaProvider()
        for chunk in provider.chat(outbound_input, streaming=state.streaming):
            if should_stream_stdout:
                print(chunk, end="", flush=True)
            chunks.append(chunk)
        if should_stream_stdout:
            print()
    elif state.active_model == "openrouter":
        from tuochat.cli.session import conversation_history_for_openrouter  # noqa: PLC0415

        if not isinstance(state.provider, OpenRouterProvider):
            raise RuntimeError("OpenRouter mode requires an OpenRouter provider.")
        history = conversation_history_for_openrouter(state)
        try:
            for chunk in state.provider.chat(
                outbound_input,
                streaming=state.streaming,
                additional_context=state.server_context or None,
                history=history,
                system_prompt=state.conv.system_prompt,
            ):
                if first_token_at_iso is None and chunk:
                    first_token_at_iso = utc_now_iso()
                if should_stream_stdout:
                    print(chunk, end="", flush=True)
                chunks.append(chunk)
        except OpenRouterAPIError as exc:
            raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
        if should_stream_stdout:
            print()
    else:
        if not isinstance(state.provider, DuoProvider):
            raise RuntimeError("Duo mode requires a Duo provider.")
        for chunk in state.provider.chat(
            outbound_input,
            resource_id=state.conv.resource_id,
            streaming=state.streaming,
            cancel=lambda: False,
            additional_context=state.server_context or None,
        ):
            if first_token_at_iso is None and chunk:
                first_token_at_iso = utc_now_iso()
            if should_stream_stdout:
                print(chunk, end="", flush=True)
            chunks.append(chunk)
        if should_stream_stdout:
            print()
    elapsed_seconds = time.perf_counter() - started_at
    full_response = "".join(chunks)

    # Record observability for Duo turns only
    if state.active_model not in {"eliza", "openrouter"}:
        obs_total_ms = int(elapsed_seconds * 1000)
        obs_input_tokens = estimate_tokens(outbound_input)
        obs_output_tokens = estimate_tokens(full_response)
        obs_ttfb_ms: int | None = None
        if first_token_at_iso is not None:
            obs_ttfb_ms = obs_ms_between(request_started_at_iso, first_token_at_iso)
        obs_tpt: float | None = None
        if obs_output_tokens > 0:
            obs_tpt = obs_total_ms / obs_output_tokens
        obs_diagnostics = getattr(state.provider, "get_last_chat_diagnostics", lambda: None)()
        obs_req_id = obs_diagnostics.request_id if obs_diagnostics is not None else None
        state.store.save_observability_row(
            ObservabilityRow(
                provider="gitlab_duo",
                status="completed",
                request_started_at=request_started_at_iso,
                finished_at=utc_now_iso(),
                request_tokens=obs_input_tokens,
                total_response_ms=obs_total_ms,
                conversation_id=state.conv.id,
                request_id=obs_req_id,
                response_tokens=obs_output_tokens if obs_output_tokens > 0 else None,
                first_token_at=first_token_at_iso,
                time_to_first_token_ms=obs_ttfb_ms,
                time_per_token_ms=obs_tpt,
            )
        )
    if not should_stream_stdout and not json_output:
        print(full_response)
    return persist_turn(
        state,
        user_input=user_input,
        outbound_input=outbound_input,
        full_response=full_response,
        interrupted=interrupted,
    )


def print_headless_json(result: HeadlessExecution, output_file: Path | None) -> None:
    """Render a headless command result as JSON."""
    payload = {
        "conversation_id": result.conversation.id,
        "title": result.conversation.title,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "response_text": result.response_text,
        "saved_markdown_path": str(result.markdown_path) if result.markdown_path is not None else None,
        "output_file": str(output_file) if output_file is not None else None,
        "extracted_file_paths": [str(path) for path in result.extracted_paths],
    }
    print(json_dumps(payload, indent=True))


def run_headless_ask(
    cfg: TuochatConfig,
    command: HeadlessAskCommand,
    *,
    build_provider: Callable[[TuochatConfig, int | None], DuoProvider],
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
) -> int:
    """Execute a new headless chat request."""
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
        system_prompt, prompt_sources = compose_system_prompt(
            command.system_prompt,
            load_custom_instruction_sections(cfg, mode="headless"),
        )
        conversation = Conversation(
            resource_id=command.resource_id or cfg.chat.default_resource_id,
            system_prompt=system_prompt,
            cwd=str(Path.cwd()),
        )
        state = build_headless_state(
            cfg,
            conversation=conversation,
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
        try:
            result = execute_turn(state, user_input, json_output=command.json_output)
        finally:
            store.close()
        save_output_file(command.output_file, result.response_text)
        if command.json_output:
            print_headless_json(result, command.output_file)
        return 0
    except (HeadlessInteractiveActionRequired, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def run_headless_continue(
    cfg: TuochatConfig,
    command: HeadlessContinueCommand,
    *,
    build_provider: Callable[[TuochatConfig, int | None], DuoProvider],
    build_store: Callable[[TuochatConfig], ConversationStore | NullConversationStore],
    resolve_conversation_id: Callable[[ConversationStore | NullConversationStore, str], str | None],
) -> int:
    """Continue a saved conversation non-interactively."""
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
            if is_ongoing_conversation_id(command.id):
                if command.model != "duo":
                    raise ValueError('The special conversation ID "ongoing" is only supported with the Duo model.')
                conversation, prompt_sources = load_or_create_ongoing_conversation(cfg, store)
                resumed_context_pending = False
            else:
                conversation_id = resolve_conversation_id(store, command.id)
                if conversation_id is None:
                    return 1
                loaded_conversation = store.get_conversation(conversation_id)
                if loaded_conversation is None:
                    print(f"Conversation {conversation_id} not found.", file=sys.stderr)
                    return 1
                conversation = loaded_conversation
                conversation.messages = store.get_messages(conversation_id)
                prompt_sources = (
                    ["saved conversation prompt (embedded in transcript)"] if conversation.system_prompt else []
                )
                resumed_context_pending = bool(conversation.messages)
            state = build_headless_state(
                cfg,
                conversation=conversation,
                store=store,
                provider=provider,
                streaming=resolve_streaming_enabled(cfg, no_stream_requested=command.no_stream),
                active_model=command.model,
                prompt_sources=prompt_sources,
                timeout_override=command.timeout,
                resumed_context_pending=resumed_context_pending,
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
            result = execute_turn(state, user_input, json_output=command.json_output)
        finally:
            store.close()
        save_output_file(command.output_file, result.response_text)
        if command.json_output:
            print_headless_json(result, command.output_file)
        return 0
    except (HeadlessInteractiveActionRequired, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
