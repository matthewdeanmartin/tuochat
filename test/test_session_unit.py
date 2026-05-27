"""Unit tests for session helpers and state transitions."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tuochat.cli import session
from tuochat.cli.models import ReplState
from tuochat.config import TuochatConfig
from tuochat.constants import NO_CODE_MODE_REPLACEMENT
from tuochat.models import Conversation, Message, Role


def make_cfg(tmp_path: Path) -> TuochatConfig:
    cfg = TuochatConfig()
    cfg.config_dir = tmp_path / "config"
    cfg.data_dir = tmp_path / "data"
    cfg.log_dir = tmp_path / "logs"
    cfg.gitlab.host = "https://gitlab.com"
    cfg.gitlab.token = "glpat-test"
    return cfg


def make_state(
    tmp_path: Path,
    *,
    cfg: TuochatConfig | None = None,
    conv: Conversation | None = None,
    store: object | None = None,
) -> ReplState:
    return ReplState(
        conv=conv or Conversation(title="Session Test"),
        store=store or MagicMock(),
        provider=object(),
        cfg=cfg or make_cfg(tmp_path),
        streaming=True,
        command_log=[],
        pending_attachment_messages=[],
        pending_attachment_names=[],
        server_context=[],
    )


def test_blind_mode_enabled_reads_state_like_and_config_like_objects(tmp_path):
    cfg = SimpleNamespace(chat=SimpleNamespace(blind=True))
    state = make_state(tmp_path, cfg=cfg)
    state.blind_mode = False
    state.cfg = cfg

    assert session.blind_mode_enabled(SimpleNamespace(blind_mode=True)) is True
    assert session.blind_mode_enabled(cfg) is True
    assert session.blind_mode_enabled(state) is False
    assert session.blind_mode_enabled(object()) is False


def test_sync_conversation_artifacts_skips_archive_when_no_write_enabled():
    cfg = SimpleNamespace(chat=SimpleNamespace(no_write=True))

    with patch("tuochat.cli.session.archive_sync_conversation_artifacts") as archive_sync:
        result = session.sync_conversation_artifacts(cfg, Conversation(title="Skip"))

    assert result == (None, None, [])
    archive_sync.assert_not_called()


def test_sync_conversation_artifacts_uses_prompt_write_approval_when_needed():
    cfg = SimpleNamespace(chat=SimpleNamespace(no_write=False, approve_writes=True, write_here_mode=True))
    conv = Conversation(title="Approval")

    with patch(
        "tuochat.cli.session.archive_sync_conversation_artifacts", return_value=("dir", "md", [])
    ) as archive_sync:
        result = session.sync_conversation_artifacts(cfg, conv)

    assert result == ("dir", "md", [])
    assert archive_sync.call_args.args == (cfg, conv)
    assert archive_sync.call_args.kwargs["approve_write"] is session.prompt_write_here_approval


def test_open_path_uses_webbrowser_for_non_windows_paths(tmp_path):
    path = tmp_path / "note.txt"

    with (
        patch.object(session.sys, "platform", "linux"),
        patch("tuochat.cli.session.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run_open,
    ):
        ok, message = session.open_path(path)

    assert ok is True
    assert message == f"opened {path}"
    run_open.assert_called_once_with(
        ["xdg-open", str(path.resolve())],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_open_path_reports_failure_when_webbrowser_cannot_open(tmp_path):
    path = tmp_path / "note.txt"

    with (
        patch.object(session.sys, "platform", "linux"),
        patch("tuochat.cli.session.subprocess.run", return_value=SimpleNamespace(returncode=1)),
    ):
        ok, message = session.open_path(path)

    assert ok is False
    assert message == f"unable to open {path}"


def test_record_log_event_initializes_log_and_trims_to_max(tmp_path):
    state = make_state(tmp_path)
    state.command_log = [{"kind": str(index)} for index in range(session.COMMAND_LOG_MAX)]

    session.record_log_event(state, "turn", detail="value")

    assert len(state.command_log) == session.COMMAND_LOG_MAX
    assert state.command_log[0]["kind"] == "1"
    assert state.command_log[-1]["kind"] == "turn"
    assert state.command_log[-1]["detail"] == "value"


def test_persist_chat_preferences_skips_when_required_attrs_are_missing(tmp_path):
    state = make_state(tmp_path, cfg=SimpleNamespace(chat=SimpleNamespace(no_write=False)))

    with patch("tuochat.config.save_config") as save_config:
        session.persist_chat_preferences(state)

    save_config.assert_not_called()


def test_persist_chat_preferences_updates_config_and_saves(tmp_path):
    cfg = make_cfg(tmp_path)
    state = make_state(tmp_path, cfg=cfg)
    state.config_path = tmp_path / "config.toml"
    state.dot_timer_enabled = True
    state.quiet = True
    state.no_banner = True
    state.blind_mode = True

    with patch("tuochat.config.save_config") as save_config:
        session.persist_chat_preferences(state)

    assert cfg.chat.dot_timer is True
    assert cfg.chat.quiet is True
    assert cfg.chat.no_banner is True
    assert cfg.chat.blind is True
    save_config.assert_called_once_with(cfg, state.config_path)


def test_toggle_write_here_mode_rejects_filesystem_root(capsys, tmp_path):
    state = make_state(tmp_path, cfg=SimpleNamespace(chat=SimpleNamespace(write_here_mode=False)))

    with patch("tuochat.cli.session.cwd_is_filesystem_root", return_value=True):
        session.toggle_write_here_mode(state, True)

    assert state.cfg.chat.write_here_mode is False
    captured = capsys.readouterr()
    assert "filesystem root" in captured.err


def test_toggle_write_here_mode_enables_and_disables_session_setting(capsys, tmp_path):
    state = make_state(tmp_path, cfg=SimpleNamespace(chat=SimpleNamespace(write_here_mode=False)))

    with patch("tuochat.cli.session.cwd_is_filesystem_root", return_value=False):
        session.toggle_write_here_mode(state, True)
        session.toggle_write_here_mode(state, False)

    assert state.cfg.chat.write_here_mode is False
    captured = capsys.readouterr()
    assert "Write-here mode enabled for this session." in captured.out
    assert "Write-here mode disabled for this session." in captured.out


def test_start_long_request_notifier_warns_only_before_first_output(capsys, tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.notifications.long_request_bell_enabled = True
    cfg.notifications.long_request_bell_seconds = 20

    class FakeEvent:
        def wait(self, delay: float) -> bool:
            return False

        def set(self) -> None:
            return None

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target

        def start(self) -> None:
            self.target()

        def join(self, timeout: float | None = None) -> None:
            _ = timeout

    with (
        patch("tuochat.cli.session.threading.Event", return_value=FakeEvent()),
        patch("tuochat.cli.session.threading.Thread", FakeThread),
        patch("tuochat.cli.session.emit_long_request_notification") as notify,
    ):
        session.start_long_request_notifier(cfg, should_warn=lambda: False)

    assert capsys.readouterr().err == ""
    notify.assert_not_called()

    with (
        patch("tuochat.cli.session.threading.Event", return_value=FakeEvent()),
        patch("tuochat.cli.session.threading.Thread", FakeThread),
        patch("tuochat.cli.session.emit_long_request_notification") as notify,
    ):
        session.start_long_request_notifier(cfg, should_warn=lambda: True)

    assert "[Still waiting after 20 seconds...]" in capsys.readouterr().err
    notify.assert_called_once()


def test_toggle_approve_writes_is_idempotent_and_updates_setting(capsys, tmp_path):
    state = make_state(tmp_path, cfg=SimpleNamespace(chat=SimpleNamespace(approve_writes=False)))

    session.toggle_approve_writes(state, True)
    session.toggle_approve_writes(state, True)

    assert state.cfg.chat.approve_writes is True
    captured = capsys.readouterr()
    assert "Approve-writes enabled for this session." in captured.out
    assert "Approve-writes is already enabled." in captured.out


def test_toggle_no_write_disables_local_writes_and_clears_saved_artifacts(capsys, tmp_path):
    cfg = make_cfg(tmp_path)
    old_store = MagicMock()
    new_store = MagicMock()
    state = make_state(tmp_path, cfg=cfg, store=old_store)
    state.last_saved_markdown_path = tmp_path / "conv.md"
    state.last_saved_extracted_count = 2
    state.last_saved_virtual_file_notice = True

    with patch("tuochat.cli.session.build_store", return_value=new_store):
        session.toggle_no_write(state, True)

    assert state.cfg.chat.no_write is True
    assert state.local_writes_enabled is False
    assert state.store is new_store
    assert state.last_saved_markdown_path is None
    assert state.last_saved_extracted_count == 0
    assert state.last_saved_virtual_file_notice is False
    old_store.close.assert_called_once_with()
    new_store.save_conversation.assert_not_called()
    captured = capsys.readouterr()
    assert "Local writes disabled for this session." in captured.out


def test_toggle_no_write_reenables_and_saves_existing_messages(capsys, tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.chat.no_write = True
    conv = Conversation(title="Persist")
    conv.add_message(Role.USER.value, "hello")
    conv.add_message(Role.ASSISTANT.value, "hi")
    old_store = MagicMock()
    new_store = MagicMock()
    state = make_state(tmp_path, cfg=cfg, conv=conv, store=old_store)

    with patch("tuochat.cli.session.build_store", return_value=new_store):
        session.toggle_no_write(state, False)

    assert state.cfg.chat.no_write is False
    assert state.local_writes_enabled is True
    assert state.store is new_store
    new_store.save_conversation.assert_called_once_with(conv)
    assert new_store.save_message.call_count == 2
    captured = capsys.readouterr()
    assert "Local writes enabled for this session." in captured.out


def test_handle_server_context_command_adds_and_updates_inline_entries(capsys, tmp_path):
    state = make_state(tmp_path)

    session.handle_server_context_command("/server-add", "FILE readme hello", state)
    session.handle_server_context_command("/server-add", "FILE readme updated", state)

    assert state.server_context == [{"category": "FILE", "name": "readme", "content": "updated"}]
    captured = capsys.readouterr()
    assert "Added FILE context item: readme (5 chars)" in captured.out
    assert "Updated FILE context item: readme" in captured.out


def test_handle_server_context_command_reads_file_content(capsys, tmp_path):
    content_path = tmp_path / "snippet.txt"
    content_path.write_text("alpha\nbeta", encoding="utf-8")
    state = make_state(tmp_path)

    session.handle_server_context_command("/server-add", f"SNIPPET snippet {content_path}", state)

    assert state.server_context == [{"category": "SNIPPET", "name": "snippet", "content": "alpha\nbeta"}]
    captured = capsys.readouterr()
    assert "Read 10 chars from" in captured.out


def test_handle_server_context_command_can_query_show_and_clear_items(capsys, tmp_path):
    state = make_state(tmp_path)
    state.server_context = [
        {"category": "FILE", "name": "README.md", "content": "first line\nsecond line"},
        {"category": "ISSUE", "name": "123", "content": ""},
    ]

    session.handle_server_context_command("/server-query", "read", state)
    session.handle_server_context_command("/server-get-item-content", "README.md", state)
    session.handle_server_context_command("/server-clear", "", state)

    assert state.server_context == []
    captured = capsys.readouterr()
    assert "FILE — README.md" in captured.out
    assert "first line\nsecond line" in captured.out
    assert "Cleared 2 server context item(s)." in captured.out


def test_latest_assistant_message_returns_latest_nonempty_assistant_content():
    conv = Conversation(title="Messages")
    conv.messages = [
        Message(role=Role.USER.value, content="hi"),
        Message(role=Role.ASSISTANT.value, content=""),
        Message(role=Role.ASSISTANT.value, content="answer"),
    ]

    assert session.latest_assistant_message(conv) == "answer"


@pytest.mark.skipif(importlib.util.find_spec("tkinter") is None, reason="tkinter is not available")
def test_copy_to_clipboard_uses_tkinter_when_available():
    root = MagicMock()

    with patch("tkinter.Tk", return_value=root):
        ok, message = session.copy_to_clipboard("hello")

    assert ok is True
    assert message == "clipboard updated with tkinter"
    root.withdraw.assert_called_once_with()
    root.clipboard_append.assert_called_once_with("hello")
    root.destroy.assert_called_once_with()


@pytest.mark.skipif(importlib.util.find_spec("tkinter") is None, reason="tkinter is not available")
def test_copy_to_clipboard_falls_back_to_platform_command_when_tkinter_fails():
    # Note: this test is supposed to check for fallback when tkinter isn't avail
    # but the test can't run if tkinter is missing!
    completed = subprocess.CompletedProcess(args=["pbcopy"], returncode=0)

    with (
        patch("tkinter.Tk", side_effect=RuntimeError("tk failed")),
        patch.object(session.sys, "platform", "darwin"),
        patch("tuochat.cli.session.subprocess.run", return_value=completed) as run_process,
    ):
        ok, message = session.copy_to_clipboard("hello")

    assert ok is True
    assert message == "clipboard updated with pbcopy"
    run_process.assert_called_once()


def test_extract_template_message_metadata_handles_valid_and_invalid_payloads():
    valid = Message(extras_json='{"template": {"name": "recipe"}}')
    invalid = Message(extras_json="not json")
    missing = Message(extras_json='{"other": 1}')

    assert session.extract_template_message_metadata(valid) == {"name": "recipe"}
    assert session.extract_template_message_metadata(invalid) is None
    assert session.extract_template_message_metadata(missing) is None


def test_reset_repl_state_clears_transient_fields_and_preserves_prompt_and_resource(tmp_path):
    cfg = make_cfg(tmp_path)
    conv = Conversation(title="Old", resource_id="gid://1", system_prompt="embedded")
    conv.add_message(Role.USER.value, "hello")
    state = make_state(tmp_path, cfg=cfg, conv=conv)
    state.base_resource_id = "gid://base"
    state.base_system_prompt = "Base prompt"
    state.pending_custom_path = tmp_path / "custom.md"
    state.last_user_input = "previous"
    state.last_include_path = tmp_path / "file.py"
    state.last_include_hash = "hash"
    state.last_include_size = 42
    state.last_include_message = "include"
    state.pending_attachment_messages = ["attachment"]
    state.pending_attachment_names = ["file.py"]
    state.pending_template_metadata = {"name": "template"}
    state.last_candidates = [tmp_path / "candidate.py"]
    state.command_log = [{"kind": "turn"}]
    state.last_saved_markdown_path = tmp_path / "saved.md"
    state.last_saved_extracted_count = 3
    state.last_saved_virtual_file_notice = True
    state.server_context = [{"category": "FILE", "name": "a", "content": "b"}]
    state.active_classification = "SECRET"

    with (
        patch("tuochat.cli.session.load_custom_instruction_sections", return_value=["section"]) as load_sections,
        patch("tuochat.cli.session.compose_system_prompt", return_value=("Composed prompt", ["custom source"])),
        patch("tuochat.cli.session.print_chat_summary"),
        patch("tuochat.cli.session.print_saved_conversation_files"),
        patch("tuochat.cli.session.print_system_prompt_sources"),
    ):
        session.reset_repl_state(state)

    assert state.conv.resource_id == "gid://base"
    assert state.conv.system_prompt == "Composed prompt"
    assert state.active_system_prompt_sources == ["custom source"]
    assert state.last_user_input is None
    assert state.last_include_path is None
    assert state.last_include_hash is None
    assert state.last_include_size is None
    assert state.last_include_message is None
    assert state.pending_attachment_messages == []
    assert state.pending_attachment_names == []
    assert state.pending_template_metadata is None
    assert state.last_candidates is None
    assert state.command_log == []
    assert state.last_saved_markdown_path is None
    assert state.last_saved_extracted_count == 0
    assert state.last_saved_virtual_file_notice is False
    assert state.server_context == []
    assert state.active_classification is None
    load_sections.assert_called_once_with(cfg, extra_paths=[state.pending_custom_path])


def test_reset_repl_state_prompts_for_classification_when_enabled(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.classification.enabled = True
    cfg.classification.ask_per_conversation = True
    state = make_state(tmp_path, cfg=cfg)

    with (
        patch("tuochat.cli.session.load_custom_instruction_sections", return_value=[]),
        patch("tuochat.cli.session.compose_system_prompt", return_value=("prompt", ["source"])),
        patch("tuochat.cli.session.prompt_classification", return_value="PUBLIC"),
        patch("tuochat.cli.session.print_system_prompt_sources"),
    ):
        session.reset_repl_state(state)

    assert state.active_classification == "PUBLIC"


def test_update_saved_conversation_artifacts_records_markdown_path_and_count(tmp_path):
    state = make_state(tmp_path)
    md_path = tmp_path / "saved.md"
    extracted = [tmp_path / "one.py", tmp_path / "two.py"]

    session.update_saved_conversation_artifacts(state, md_path, extracted)

    assert state.last_saved_markdown_path == md_path
    assert state.last_saved_extracted_count == 2
    assert state.last_saved_virtual_file_notice is True


def test_provider_for_attempt_uses_timeout_override_and_multiplier(tmp_path):
    state = make_state(tmp_path)
    state.timeout_override = 7

    with patch("tuochat.cli.session.build_provider", return_value="provider") as build_provider:
        provider = session.provider_for_attempt(state, timeout_multiplier=3)

    assert provider == "provider"
    build_provider.assert_called_once_with(state.cfg, timeout_override=21)


def test_stream_safe_display_length_holds_back_secret_sized_tail():
    with patch("tuochat.cli.session.display_text", return_value=("x" * 90, False, False)):
        displayed = session.stream_safe_display_length(
            "ignored",
            mask_output=True,
            no_code_mode=False,
            known_secrets=["s" * 50],
        )

    assert displayed == "x" * 40


def test_stream_safe_display_length_replaces_open_code_block_in_no_code_mode():
    displayed = session.stream_safe_display_length(
        "prefix```python\nprint('x')",
        mask_output=False,
        no_code_mode=True,
    )

    assert displayed == f"prefix{NO_CODE_MODE_REPLACEMENT}"


def test_send_chat_turn_abort_on_connection_error_leaves_conversation_unchanged(capsys, tmp_path):
    cfg = make_cfg(tmp_path)
    store = MagicMock()
    state = make_state(tmp_path, cfg=cfg, store=store)

    class FailingProvider:
        def chat(self, *args, **kwargs):
            raise ConnectionError("boom")
            yield ""

    class DummyEvent:
        def set(self) -> None:
            return None

    with (
        patch("tuochat.cli.session.validate_user_request", return_value=True),
        patch("tuochat.cli.session.provider_for_attempt", return_value=FailingProvider()),
        patch("tuochat.cli.session.start_long_request_notifier", return_value=(DummyEvent(), None)),
        patch("tuochat.cli.session.start_dot_timer", return_value=(DummyEvent(), None)),
        patch("tuochat.cli.session.known_secret_values", return_value=[]),
        patch("tuochat.cli.session.print_chat_diagnostics"),
        patch("tuochat.cli.session.retry_failure_action", return_value="abort"),
    ):
        session.send_chat_turn(state, "hello")

    assert state.conv.messages == []
    store.save_conversation.assert_not_called()
    store.save_message.assert_not_called()
    captured = capsys.readouterr()
    assert "Request aborted. Conversation state was left unchanged." in captured.out
    assert "[Connection error: boom]" in captured.err


def test_send_chat_turn_preserves_sandbox_attachment_queued_after_response(tmp_path):
    cfg = make_cfg(tmp_path)
    store = MagicMock()
    state = make_state(tmp_path, cfg=cfg, store=store)
    state.pending_attachment_names = ["existing.txt"]
    state.pending_attachment_messages = ["existing attachment"]
    state.code_interpreter_enabled = True

    class SuccessfulProvider:
        def chat(self, *args, **kwargs):
            _ = args, kwargs
            yield "```javascript\nconsole.log(42)\n```"

    def queue_sandbox_attachment(response: str, queued_state: ReplState) -> bool:
        assert "console.log(42)" in response
        queued_state.pending_attachment_names.append("[sandbox]")
        queued_state.pending_attachment_messages.append("sandbox attachment")
        return True

    class DummyEvent:
        def set(self) -> None:
            return None

    with (
        patch("tuochat.cli.session.validate_user_request", return_value=True),
        patch("tuochat.cli.session.provider_for_attempt", return_value=SuccessfulProvider()),
        patch("tuochat.cli.session.start_long_request_notifier", return_value=(DummyEvent(), None)),
        patch("tuochat.cli.session.start_dot_timer", return_value=(DummyEvent(), None)),
        patch("tuochat.cli.session.known_secret_values", return_value=[]),
        patch("tuochat.cli.session.sync_conversation_artifacts", return_value=(None, None, [])),
        patch("tuochat.sandbox.integration.handle_sandbox_response", side_effect=queue_sandbox_attachment),
    ):
        session.send_chat_turn(state, "hello")

    assert state.pending_attachment_names == ["[sandbox]"]
    assert state.pending_attachment_messages == ["sandbox attachment"]
