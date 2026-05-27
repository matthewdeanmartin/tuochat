from __future__ import annotations

from types import SimpleNamespace

from tuochat.cli.command_models import DiffCommand, FilesApproveCommand, FilesDeleteCommand
from tuochat.cli.commands import files_cmd
from tuochat.cli.dispatch import command_from_args
from tuochat.cli.entrypoint import build_parser
from tuochat.cli.repl import handle_slash_command
from tuochat.cli.session import ReplState, resolve_streaming_enabled
from tuochat.config import TuochatConfig
from tuochat.models import Conversation
from tuochat.persistence.store import ConversationStore


def test_run_files_approve_renames_safe_checks_and_skips_clashes(capsys, tmp_path):
    safe_check = tmp_path / "safe.py.check"
    clash_target = tmp_path / "clash.py"
    clash_check = tmp_path / "clash.py.check"
    safe_check.write_text("print('safe')\n", encoding="utf-8")
    clash_target.write_text("print('live')\n", encoding="utf-8")
    clash_check.write_text("print('draft')\n", encoding="utf-8")

    result = files_cmd.run_files_approve(tmp_path)

    assert result == 0
    assert safe_check.exists() is False
    assert (tmp_path / "safe.py").read_text(encoding="utf-8") == "print('safe')\n"
    assert clash_check.is_file()
    captured = capsys.readouterr()
    assert "Approved 1 .check file(s)." in captured.out
    assert "Skipped due to name clashes:" in captured.out


def test_run_files_delete_respects_confirmation(capsys, tmp_path):
    doomed = tmp_path / "draft.py.check"
    doomed.write_text("x\n", encoding="utf-8")

    result = files_cmd.run_files_delete(tmp_path, prompt=lambda prompt: "n")

    assert result == 0
    assert doomed.is_file()
    captured = capsys.readouterr()
    assert "Delete cancelled." in captured.out


def test_run_diff_prints_pair_and_unpaired_list(capsys, tmp_path):
    live = tmp_path / "example.py"
    live.write_text("print('live')\n", encoding="utf-8")
    check = tmp_path / "example.py.check"
    check.write_text("print('draft')\n", encoding="utf-8")
    unpaired = tmp_path / "orphan.py.check"
    unpaired.write_text("print('orphan')\n", encoding="utf-8")

    result = files_cmd.run_diff(tmp_path, prompt_continue=lambda prompt: "")

    assert result == 0
    captured = capsys.readouterr()
    assert "--- example.py" in captured.out
    assert "+++ example.py.check" in captured.out
    assert "Unpaired .check files:" in captured.out
    assert "orphan.py.check" in captured.out


def test_entrypoint_parser_supports_files_and_diff_commands():
    parser = build_parser()

    args = parser.parse_args(["files", "delete", "--yes"])
    diff_args = parser.parse_args(["diff"])

    assert args.command_key == "files-delete"
    assert args.yes is True
    assert diff_args.command_key == "diff"


def test_command_from_args_builds_file_command_models():
    approve = command_from_args(SimpleNamespace(command_key="files-approve"))
    delete = command_from_args(SimpleNamespace(command_key="files-delete", yes=True))
    diff = command_from_args(SimpleNamespace(command_key="diff"))

    assert approve == FilesApproveCommand()
    assert delete == FilesDeleteCommand(yes=True)
    assert diff == DiffCommand()


def test_resolve_streaming_enabled_holds_non_streaming_when_flag_is_off():
    cfg = TuochatConfig()
    cfg.chat.streaming = False
    cfg.chat.enable_no_stream = False

    assert resolve_streaming_enabled(cfg) is True
    assert resolve_streaming_enabled(cfg, no_stream_requested=True) is True


def test_slash_stream_off_is_blocked_while_flag_is_off(capsys, tmp_path):
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path / "data"
    cfg.chat.enable_no_stream = False
    with ConversationStore(tmp_path / "tuochat.db") as store:
        state = ReplState(
            conv=Conversation(title="Streaming Gate"),
            store=store,
            provider=object(),
            cfg=cfg,
            streaming=True,
        )

        message, should_exit = handle_slash_command("/stream off", state)

    assert message is None
    assert should_exit is False
    assert state.streaming is True
    captured = capsys.readouterr()
    assert "chat.enable_no_stream = true" in captured.err
