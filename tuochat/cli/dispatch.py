"""Typed command parsing and dispatch for the CLI."""

# pylint: disable=import-outside-toplevel
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from tuochat.cli.command_models import GlobalOptions
    from tuochat.config import TuochatConfig


def run_headless_ask(*args, **kwargs):
    """Lazy proxy kept as a stable patch point for tests and callers."""
    from tuochat.cli.commands.headless_cmd import run_headless_ask as impl  # noqa: E402

    return impl(*args, **kwargs)


def run_headless_continue(*args, **kwargs):
    """Lazy proxy kept as a stable patch point for tests and callers."""
    from tuochat.cli.commands.headless_cmd import run_headless_continue as impl  # noqa: E402

    return impl(*args, **kwargs)


def build_provider(cfg: TuochatConfig, timeout: int | None = None):
    """Small adapter so command modules can inject timeout overrides."""
    # Keep provider bootstrap lazy for local-only commands.
    from tuochat.cli.bootstrap import build_provider as bootstrap_build_provider  # noqa: E402

    return bootstrap_build_provider(cfg, timeout_override=timeout)


def command_from_args(args: argparse.Namespace):
    """Translate argparse output into a typed command model."""
    # Import typed command models only after argparse has selected a command.
    from tuochat.cli.command_models import (  # noqa: E402
        ArchiveConversationCommand,
        AuthCommand,
        BagitCheckCommand,
        BagitUpdateCommand,
        ChatCommand,
        ChatLatestCommand,
        ChatNewCommand,
        ChatSendCommand,
        ChatShowCommand,
        ConfigCommand,
        DeleteConversationCommand,
        DiffCommand,
        DoctorCommand,
        ExportCommand,
        FilesApproveCommand,
        FilesDeleteCommand,
        GuiCommand,
        HeadlessAskCommand,
        HeadlessContinueCommand,
        InitCommand,
        ListConversationsCommand,
        ListCustomInstructionsCommand,
        ListFilesCommand,
        ListSkillsCommand,
        ListTemplatesCommand,
        ObservabilityCommand,
        OpenConversationCommand,
        OpenRouterCommand,
        ResumeCommand,
        SearchCommand,
        SelfcheckCommand,
        UnarchiveConversationCommand,
        UsageCommand,
    )

    key = getattr(args, "command_key", None)
    if key == "repl":
        return ChatCommand(
            prompt=getattr(args, "prompt", None),
            resource_id=getattr(args, "resource_id", None),
            no_stream=getattr(args, "no_stream", False),
            timeout=getattr(args, "timeout", None),
        )
    if key == "chat-new":
        return ChatNewCommand(
            prompt=getattr(args, "message", None),
            prompt_file=getattr(args, "prompt_file", None),
            use_stdin=getattr(args, "stdin", False),
            includes=tuple(getattr(args, "include", None) or []),
            web_urls=tuple(getattr(args, "web", None) or []),
            skill=getattr(args, "skill", None),
            template=getattr(args, "template", None),
            variables=tuple(getattr(args, "var", None) or []),
            output_file=getattr(args, "output_file", None),
            format=getattr(args, "format", "markdown"),
            no_stream=getattr(args, "no_stream", False),
            system_prompt=getattr(args, "system_prompt", None),
            resource_id=getattr(args, "resource_id", None),
            timeout=getattr(args, "timeout", None),
            model=getattr(args, "model", "duo"),
            cwd=getattr(args, "cwd", None),
        )
    if key == "chat-send":
        return ChatSendCommand(
            conversation=getattr(args, "conversation", "latest"),
            prompt=getattr(args, "message", None),
            prompt_file=getattr(args, "prompt_file", None),
            use_stdin=getattr(args, "stdin", False),
            includes=tuple(getattr(args, "include", None) or []),
            web_urls=tuple(getattr(args, "web", None) or []),
            skill=getattr(args, "skill", None),
            template=getattr(args, "template", None),
            variables=tuple(getattr(args, "var", None) or []),
            output_file=getattr(args, "output_file", None),
            format=getattr(args, "format", "markdown"),
            no_stream=getattr(args, "no_stream", False),
            timeout=getattr(args, "timeout", None),
            model=getattr(args, "model", "duo"),
            cwd=getattr(args, "cwd", None),
            restore_cwd=getattr(args, "restore_cwd", True),
            fail_if_missing=getattr(args, "fail_if_missing", False),
        )
    if key == "chat-show":
        return ChatShowCommand(
            conversation=getattr(args, "conversation", "latest"),
            format=getattr(args, "format", "markdown"),
            fail_if_missing=getattr(args, "fail_if_missing", False),
        )
    if key == "chat-latest":
        return ChatLatestCommand(format=getattr(args, "format", "markdown"))
    if key == "chat":
        return ChatCommand(
            prompt=args.prompt, resource_id=args.resource_id, no_stream=args.no_stream, timeout=args.timeout
        )
    if key == "gui":
        return GuiCommand(
            prompt=args.prompt, resource_id=args.resource_id, no_stream=args.no_stream, timeout=args.timeout
        )
    if key == "config":
        return ConfigCommand(format=args.format)
    if key == "init":
        return InitCommand(force=args.force)
    if key == "auth":
        return AuthCommand(action=getattr(args, "auth_action", None) or "login")
    if key == "openrouter":
        return OpenRouterCommand(action=getattr(args, "openrouter_action", None) or "status")
    if key == "doctor":
        return DoctorCommand(format=args.format)
    if key == "diff":
        return DiffCommand()
    if key == "usage":
        return UsageCommand(format=args.format)
    if key == "observability":
        return ObservabilityCommand(format=args.format)
    if key in {"history", "convo-list"}:
        return ListConversationsCommand(limit=args.limit, archived=getattr(args, "archived", False), format=args.format)
    if key in {"resume", "convo-resume"}:
        return ResumeCommand(id=args.id)
    if key == "convo-archive":
        return ArchiveConversationCommand(id=args.id)
    if key == "convo-unarchive":
        return UnarchiveConversationCommand(id=getattr(args, "id", None), all=getattr(args, "all", False))
    if key == "convo-delete":
        return DeleteConversationCommand(id=args.id)
    if key in {"search", "convo-search"}:
        return SearchCommand(
            query=list(args.query),
            limit=args.limit,
            title=args.title,
            after=args.after,
            before=args.before,
        )
    if key in {"export", "convo-export"}:
        return ExportCommand(id=args.id, meta=getattr(args, "meta", False))
    if key == "convo-open":
        return OpenConversationCommand(id=args.id)
    if key == "archive-bagit-update":
        return BagitUpdateCommand()
    if key == "archive-bagit-check":
        return BagitCheckCommand(format=args.format)
    if key == "context-files":
        return ListFilesCommand(format=args.format)
    if key == "context-skills":
        return ListSkillsCommand(format=args.format)
    if key == "context-templates":
        return ListTemplatesCommand(format=args.format)
    if key == "context-custom-instructions":
        return ListCustomInstructionsCommand(format=args.format)
    if key == "files-approve":
        return FilesApproveCommand()
    if key == "files-delete":
        return FilesDeleteCommand(yes=getattr(args, "yes", False))
    if key == "headless-ask":
        return HeadlessAskCommand(
            prompt=getattr(args, "message", None),
            prompt_file=args.file,
            use_stdin=args.stdin,
            includes=tuple(args.include or []),
            web_urls=tuple(getattr(args, "web", None) or []),
            skill=args.skill,
            template=args.template,
            variables=tuple(args.var or []),
            output_file=args.output_file,
            json_output=args.json,
            no_stream=args.no_stream,
            system_prompt=args.system_prompt,
            resource_id=args.resource_id,
            timeout=args.timeout,
            model=args.model,
        )
    if key == "headless-continue":
        return HeadlessContinueCommand(
            id=args.id,
            prompt=getattr(args, "message", None),
            prompt_file=args.file,
            use_stdin=args.stdin,
            includes=tuple(args.include or []),
            web_urls=tuple(getattr(args, "web", None) or []),
            skill=args.skill,
            template=args.template,
            variables=tuple(args.var or []),
            output_file=args.output_file,
            json_output=args.json,
            no_stream=args.no_stream,
            timeout=args.timeout,
            model=args.model,
        )
    if key == "selfcheck":
        return SelfcheckCommand(argv=tuple(getattr(args, "selfcheck_argv", None) or ()))
    return None


def dispatch_command(cfg: TuochatConfig, global_options: GlobalOptions, command) -> int:
    """Execute a typed command model."""
    # Import command models here for dispatch checks without eagerly importing all command handlers.
    from tuochat.cli import command_models as models  # noqa: E402
    from tuochat.cli.bootstrap import build_store, no_write_enabled  # noqa: E402

    if isinstance(command, models.ChatNewCommand):
        from tuochat.cli.commands import chat_cmd  # noqa: E402

        return chat_cmd.run_chat_new(cfg, command, build_provider=build_provider, build_store=build_store)
    if isinstance(command, models.ChatSendCommand):
        from tuochat.cli.commands import chat_cmd, conversation_cmd  # noqa: E402

        return chat_cmd.run_chat_send(
            cfg,
            command,
            build_provider=build_provider,
            build_store=build_store,
            resolve_conversation_id=conversation_cmd.resolve_conversation_id,
        )
    if isinstance(command, models.ChatShowCommand):
        from tuochat.cli.commands import chat_cmd, conversation_cmd  # noqa: E402

        return chat_cmd.run_chat_show(
            cfg,
            command,
            build_store=build_store,
            no_write_enabled=no_write_enabled,
            resolve_conversation_id=conversation_cmd.resolve_conversation_id,
        )
    if isinstance(command, models.ChatLatestCommand):
        from tuochat.cli.commands import chat_cmd  # noqa: E402

        return chat_cmd.run_chat_latest(cfg, command, build_store=build_store, no_write_enabled=no_write_enabled)
    if isinstance(command, models.ChatCommand):
        from tuochat.cli.commands import code  # noqa: E402

        return code.run_chat(cfg, global_options, command)
    if isinstance(command, models.GuiCommand):
        from tuochat.cli.commands import code  # noqa: E402

        return code.run_gui(cfg, global_options, command)
    if isinstance(command, models.ConfigCommand):
        from tuochat.cli.commands import code  # noqa: E402

        return code.run_config(cfg, command)
    if isinstance(command, models.InitCommand):
        from tuochat.cli.commands import code  # noqa: E402

        return code.run_init(global_options, command)
    if isinstance(command, models.AuthCommand):
        from tuochat.cli.commands import auth_cmd  # noqa: E402

        action = command.action
        if action == "status":
            return auth_cmd.run_status(cfg)
        if action == "logout":
            return auth_cmd.run_logout(cfg)
        if action == "refresh":
            return auth_cmd.run_refresh(cfg)
        return auth_cmd.run_login(cfg)
    if isinstance(command, models.OpenRouterCommand):
        from tuochat.cli.commands import openrouter_auth_cmd  # noqa: E402

        action = command.action
        if action == "login":
            return openrouter_auth_cmd.run_login(cfg)
        if action == "logout":
            return openrouter_auth_cmd.run_logout(cfg)
        return openrouter_auth_cmd.run_status(cfg)
    if isinstance(command, models.DoctorCommand):
        from tuochat.cli.commands import local_cmd  # noqa: E402

        return local_cmd.run_doctor(cfg, command)
    if isinstance(command, models.DiffCommand):
        from tuochat.cli.commands import files_cmd  # noqa: E402

        return files_cmd.run_diff()
    if isinstance(command, models.UsageCommand):
        from tuochat.cli.commands import local_cmd  # noqa: E402

        return local_cmd.run_usage(cfg, command, build_store=build_store, no_write_enabled=no_write_enabled)
    if isinstance(command, models.ObservabilityCommand):
        from tuochat.cli.commands import local_cmd  # noqa: E402

        return local_cmd.run_observability(cfg, command, build_store=build_store, no_write_enabled=no_write_enabled)
    if isinstance(command, models.ListConversationsCommand):
        from tuochat.cli.commands import conversation_cmd  # noqa: E402

        return conversation_cmd.run_list(cfg, command, build_store=build_store, no_write_enabled=no_write_enabled)
    if isinstance(command, models.ResumeCommand):
        from tuochat.cli.commands import code  # noqa: E402

        return code.run_resume(cfg, command)
    if isinstance(command, models.ArchiveConversationCommand):
        from tuochat.cli.commands import conversation_cmd  # noqa: E402

        return conversation_cmd.run_archive(cfg, command, build_store=build_store, no_write_enabled=no_write_enabled)
    if isinstance(command, models.UnarchiveConversationCommand):
        from tuochat.cli.commands import conversation_cmd  # noqa: E402

        return conversation_cmd.run_unarchive(cfg, command, build_store=build_store, no_write_enabled=no_write_enabled)
    if isinstance(command, models.DeleteConversationCommand):
        from tuochat.cli.commands import conversation_cmd  # noqa: E402

        return conversation_cmd.run_delete(cfg, command, build_store=build_store, no_write_enabled=no_write_enabled)
    if isinstance(command, models.SearchCommand):
        from tuochat.cli.commands import code  # noqa: E402

        return code.run_search(cfg, command)
    if isinstance(command, models.ExportCommand):
        from tuochat.cli.commands import code  # noqa: E402

        return code.run_export(cfg, command)
    if isinstance(command, models.OpenConversationCommand):
        from tuochat.cli.commands import conversation_cmd  # noqa: E402
        from tuochat.cli.session import open_path, sync_conversation_artifacts  # noqa: E402

        return conversation_cmd.run_open(
            cfg,
            command,
            build_store=build_store,
            no_write_enabled=no_write_enabled,
            sync_conversation_artifacts=sync_conversation_artifacts,
            open_path=open_path,
        )
    if isinstance(command, models.BagitUpdateCommand):
        from tuochat.cli.commands import archive_cmd  # noqa: E402
        from tuochat.persistence.archive import load_bagit_module, refresh_archive_bagit_metadata  # noqa: E402

        return archive_cmd.run_bagit_update(
            cfg,
            command,
            build_store=build_store,
            no_write_enabled=no_write_enabled,
            load_bagit_module=load_bagit_module,
            refresh_archive_bagit_metadata=refresh_archive_bagit_metadata,
        )
    if isinstance(command, models.BagitCheckCommand):
        from tuochat.cli.commands import archive_cmd  # noqa: E402
        from tuochat.persistence.archive import check_archive_bagit_status, load_bagit_module  # noqa: E402

        return archive_cmd.run_bagit_check(
            cfg,
            command,
            build_store=build_store,
            load_bagit_module=load_bagit_module,
            check_archive_bagit_status=check_archive_bagit_status,
        )
    if isinstance(command, models.ListFilesCommand):
        from tuochat.cli.commands import context_cmd  # noqa: E402

        return context_cmd.run_files(command)
    if isinstance(command, models.ListSkillsCommand):
        from tuochat.cli.commands import context_cmd  # noqa: E402

        return context_cmd.run_skills(cfg, command)
    if isinstance(command, models.ListTemplatesCommand):
        from tuochat.cli.commands import context_cmd  # noqa: E402

        return context_cmd.run_templates(cfg, command)
    if isinstance(command, models.ListCustomInstructionsCommand):
        from tuochat.cli.commands import context_cmd  # noqa: E402

        return context_cmd.run_custom_instructions(cfg, command)
    if isinstance(command, models.FilesApproveCommand):
        from tuochat.cli.commands import files_cmd  # noqa: E402

        return files_cmd.run_files_approve()
    if isinstance(command, models.FilesDeleteCommand):
        from tuochat.cli.commands import files_cmd  # noqa: E402

        return files_cmd.run_files_delete(yes=command.yes)
    if isinstance(command, models.HeadlessAskCommand):
        return run_headless_ask(cfg, command, build_provider=build_provider, build_store=build_store)
    if isinstance(command, models.SelfcheckCommand):
        from tuochat.self_pkg_mgmt.cli import main as selfcheck_main  # noqa: E402

        return selfcheck_main(list(command.argv))
    if isinstance(command, models.HeadlessContinueCommand):
        from tuochat.cli.commands import conversation_cmd  # noqa: E402

        return run_headless_continue(
            cfg,
            command,
            build_provider=build_provider,
            build_store=build_store,
            resolve_conversation_id=conversation_cmd.resolve_conversation_id,
        )
    raise ValueError(f"Unsupported command: {command!r}")
