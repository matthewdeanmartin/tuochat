"""Unit tests for CLI rendering helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from tuochat.cli import rendering
from tuochat.config import TuochatConfig
from tuochat.models import Conversation, Message, Role


def make_conversation(*, title: str | None = "Test Conversation", system_prompt: str | None = None) -> Conversation:
    """Build a conversation with deterministic IDs for rendering tests."""
    conv = Conversation(id="conversation-12345678", title=title, system_prompt=system_prompt)
    return conv


def test_clear_screen_uses_subprocess_and_falls_back_to_ansi(monkeypatch, capsys):
    calls: list[list[str]] = []
    monkeypatch.setattr(rendering.os, "name", "nt")
    monkeypatch.setattr(rendering.subprocess, "run", lambda args, check=False: calls.append(args))

    rendering.clear_screen()

    assert calls == [["cls"]]

    def raise_oserror(args, check=False):
        raise OSError("no terminal")

    monkeypatch.setattr(rendering.subprocess, "run", raise_oserror)

    rendering.clear_screen()

    assert capsys.readouterr().out == "\033[2J\033[H"


def test_screen_transition_and_number_label(capsys):
    rendering.announce_screen_transition("Next section")

    assert capsys.readouterr().out == "\nNext section\n\n"
    assert rendering.number_label(2, blind_mode=False) == "[2]"
    assert rendering.number_label(2, blind_mode=True) == "2"


def test_print_startup_banner_includes_runtime_details(monkeypatch, capsys):
    monkeypatch.setattr(rendering, "local_now", lambda: datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    monkeypatch.setattr(rendering, "python_version_string", lambda: "3.14.0")

    rendering.print_startup_banner()

    output = capsys.readouterr().out
    assert "Version:" in output
    assert "Date: 2025-01-02 03:04:05 UTC" in output
    assert "Python: 3.14.0" in output
    assert "Help: /help in chat" in output


def test_print_session_intro_respects_banner_and_quiet(monkeypatch, capsys):
    state = SimpleNamespace(cfg=TuochatConfig(), no_banner=False, quiet=False)
    calls: list[str] = []
    monkeypatch.setattr(rendering, "print_startup_banner", lambda: calls.append("banner"))
    monkeypatch.setattr(rendering, "print_startup_skills_summary", lambda cfg: calls.append("skills"))
    monkeypatch.setattr(rendering, "print_system_prompt_sources", lambda state: calls.append("sources"))
    monkeypatch.setattr(rendering, "submit_key_hint", lambda: "Ctrl+D")

    rendering.print_session_intro(state)

    output = capsys.readouterr().out
    assert calls == ["banner", "skills", "sources"]
    assert "Paste your message and submit with Ctrl+D" in output
    assert "Ctrl+C cancels the current draft" in output
    assert "use '/quit' or '/exit' to exit" in output

    calls.clear()
    quiet_state = SimpleNamespace(cfg=TuochatConfig(), no_banner=True, quiet=True)
    rendering.print_session_intro(quiet_state)
    assert calls == ["sources"]


def test_system_prompt_and_notice_renderers(capsys):
    rendering.print_system_prompt_sources(SimpleNamespace(active_system_prompt_sources=[]))
    rendering.print_system_prompt_sources(SimpleNamespace(active_system_prompt_sources=["base.md", "team.md"]))
    rendering.print_mask_notice(SimpleNamespace(conv=SimpleNamespace(id="abcdefgh1234")))
    rendering.print_no_code_mode_notice(SimpleNamespace(conv=SimpleNamespace(id="abcdefgh1234")))

    captured = capsys.readouterr()
    assert "System prompt sources: (none)" in captured.out
    assert "  - base.md" in captured.out
    assert "/resume abcdefgh" in captured.err
    assert "/no-code-mode off" in captured.err


def test_print_conversation_transcript_handles_blind_mode_and_empty_conversations(capsys):
    conv = make_conversation(title=None)
    conv.messages = [
        Message(role=Role.USER.value, content="hello"),
        Message(role=Role.ASSISTANT.value, content="world"),
    ]

    rendering.print_conversation_transcript(conv, blind_mode=False)
    rendering.print_conversation_transcript(make_conversation(), blind_mode=True)

    output = capsys.readouterr().out
    assert "Resumed: Untitled" in output
    assert "you>" in output
    assert "assistant>" in output
    assert "(conversation is empty)" in output
    assert "Next conversation" in output
    assert "End conversation" in output


def test_print_masked_conversation_transcript_masks_and_reports(monkeypatch, capsys):
    conv = make_conversation()
    conv.messages = [
        Message(role=Role.USER.value, content="user text"),
        Message(role=Role.ASSISTANT.value, content="assistant text"),
    ]
    state = SimpleNamespace(
        conv=conv,
        blind_mode=False,
        mask_output=True,
        no_code_mode=True,
        cfg=TuochatConfig(),
    )

    displays = iter(
        [
            ("masked user", True, False),
            ("masked assistant", False, True),
        ]
    )
    monkeypatch.setattr(rendering, "known_secret_values", lambda cfg: {"secret"})
    monkeypatch.setattr(rendering, "display_text", lambda text, **kwargs: next(displays))
    notices: list[str] = []
    monkeypatch.setattr(rendering, "print_mask_notice", lambda state: notices.append("mask"))
    monkeypatch.setattr(rendering, "print_no_code_mode_notice", lambda state: notices.append("code"))

    rendering.print_masked_conversation_transcript(state)

    output = capsys.readouterr().out
    assert "masked user" in output
    assert "masked assistant" in output
    assert notices == ["mask", "code"]


def test_preview_and_command_log_helpers(capsys):
    assert rendering.one_line_preview("hello\n   world", limit=50) == "hello world"
    assert rendering.one_line_preview("   ", limit=50) == "(empty)"

    rendering.print_command_log(SimpleNamespace(command_log=[]))
    rendering.print_command_log(
        SimpleNamespace(
            command_log=[
                {"at": "10:00:00", "kind": "slash", "command": "/help"},
                {
                    "at": "10:01:00",
                    "kind": "turn",
                    "input_tokens": 12,
                    "output_tokens": 34,
                    "request_preview": "req",
                    "response_preview": "resp",
                },
                {"at": "10:02:00", "kind": "event", "detail": "other"},
            ]
        )
    )

    output = capsys.readouterr().out
    assert "No local log entries for the current conversation yet." in output
    assert "[1] 10:00:00 slash  /help" in output
    assert "[2] 10:01:00 turn   in=12 out=34 req=req resp=resp" in output
    assert "[3] 10:02:00 event" in output


def test_context_usage_summary_and_markdown_helpers(monkeypatch):
    conv = make_conversation(system_prompt="system")
    conv.messages = [Message(role=Role.USER.value, content="user"), Message(role=Role.ASSISTANT.value, content="reply")]
    state = SimpleNamespace(cfg=SimpleNamespace(chat=SimpleNamespace(context_window_tokens=1000)), conv=conv)
    monkeypatch.setattr(rendering, "estimate_tokens", lambda text: len(text))

    used, remaining = rendering.context_usage_summary(state, "pending")

    assert used == len("system\nuser\nreply\npending")
    assert remaining == 1000 - used
    assert rendering.humanize_report_key("request_id") == "Request ID"
    assert rendering.render_markdown_config(
        {"chat": {"timeout": 30, "flags": ["a", "b"]}, "empty": []},
        title="Config",
    ).startswith("# Config")


def test_print_turn_estimate_and_verbose_context(monkeypatch, capsys):
    monkeypatch.setattr(rendering, "estimate_token_cost", lambda input_tokens, output_tokens: (0.12, 0.34, 0.46))
    monkeypatch.setattr(rendering, "format_cost", lambda value: f"${value:.2f}")
    monkeypatch.setattr(rendering, "context_usage_summary", lambda state, pending_user_input=None: (12, 88))

    rendering.print_turn_estimate(10, 20, verbose=False)
    rendering.print_turn_estimate(10, 20, verbose=True)
    rendering.print_verbose_context(
        SimpleNamespace(cfg=SimpleNamespace(chat=SimpleNamespace(context_window_tokens=100)))
    )

    output = capsys.readouterr().out
    assert "Estimate: in=10 out=20 cost=$0.46" in output
    assert "Estimate: in=10 out=20 cost=$0.46 (input=$0.12 output=$0.34)" in output
    assert "Context Used: 12" in output
    assert "Context Remaining: 88" in output


def test_print_expiration_warning_and_timeout_limits(monkeypatch, capsys):
    cfg = TuochatConfig()
    cfg.chat.conversation_expiration_days = 14
    cfg.config_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        rendering,
        "provider_timeout_summary",
        lambda state: {"chat": 12.5, "stream": 7.0},
    )
    state = SimpleNamespace(timeout_override=42, cfg=cfg)

    rendering.print_expiration_warning(cfg)
    rendering.print_expiration_warning(TuochatConfig())
    rendering.print_timeout_limits(state, reason="manual-check")

    output = capsys.readouterr().out
    assert "conversation expiration is enabled" in output
    assert "Reason: manual-check" in output
    assert "Chat: 12.5s" in output
    assert "Temporary Override: 42s" in output


def test_print_chat_diagnostics_handles_provider_types_and_payloads(monkeypatch, capsys):
    class FakeProvider:
        def __init__(self, diagnostics):
            self.diagnostics = diagnostics

        def get_last_chat_diagnostics(self):
            return self.diagnostics

    monkeypatch.setattr(rendering, "DuoProvider", FakeProvider)

    state = SimpleNamespace(provider=object())
    rendering.print_chat_diagnostics(state)

    state.provider = FakeProvider(None)
    rendering.print_chat_diagnostics(state, header="Chat diagnostics")

    diagnostics = SimpleNamespace(
        mode="streaming",
        subscription_id=None,
        request_id="request-1",
        fallback_reason="timeout",
        poll_attempts=3,
        poll_elapsed_seconds=1.25,
        partial_response="partial text",
        raw_events=["event-1", "event-2"],
    )
    state.provider = FakeProvider(diagnostics)
    rendering.print_chat_diagnostics(state, header="Chat diagnostics")

    output = capsys.readouterr().out
    assert "Diagnostics: unavailable for the current provider" in output
    assert "Chat diagnostics: (none)" in output
    assert "Mode: streaming" in output
    assert "Subscription ID: (none)" in output
    assert "Partial Response Chars: 12" in output
    assert "event-1" in output


def test_footer_status_and_doctor_renderers(monkeypatch, capsys, tmp_path):
    cfg = TuochatConfig(config_dir=tmp_path / "config", data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    cfg.chat.response_footer_warning_enabled = True
    cfg.chat.response_footer_warning_text = "Double-check this."
    conv = make_conversation(system_prompt="system prompt")
    conv.resource_id = "project/1"
    conv.messages = [Message(role=Role.USER.value, content="hello")]
    state = SimpleNamespace(
        cfg=cfg,
        conv=conv,
        active_model="unknown-model",
        streaming=True,
        timeout_override=None,
        mask_output=True,
        dot_timer_enabled=False,
        quiet=False,
        no_banner=False,
        blind_mode=False,
        no_code_mode=False,
        local_writes_enabled=True,
        active_classification="internal",
        active_system_prompt_sources=["base.md"],
        pending_custom_name="custom",
        pending_attachment_messages=["a", "b", "c", "d", "e", "f"],
        pending_attachment_names=["a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "f.txt"],
        last_include_path=tmp_path / "doc.md",
        last_include_size=123,
    )
    monkeypatch.setattr(rendering, "blind_mode_enabled", lambda obj: False)
    monkeypatch.setattr(rendering, "number_label", lambda index, *, blind_mode: f"[{index}]")

    rendering.print_response_footer(state, elapsed_seconds=1.23)
    rendering.print_status(state)

    monkeypatch.setenv("TUOCHAT_GITLAB_HOST", "https://gitlab.example.com")
    monkeypatch.setenv("TUOCHAT_GITLAB_TOKEN", "glpat-abcdefgh1234")
    monkeypatch.delenv("TUOCHAT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TUOCHAT_GITLAB_HOST=https://gitlab.example.com", encoding="utf-8")
    monkeypatch.setattr(
        rendering,
        "code_interpreter_runtime_details",
        lambda: {
            "installed_runtimes": ["mini-racer (V8)", "lupa"],
            "code_interpreter_ready": True,
            "preferred_javascript_runtime": "mini-racer (V8)",
            "lua_runtime": "lupa",
        },
    )
    rendering.print_doctor(cfg, streaming=True)

    output = capsys.readouterr().out
    assert "Elapsed: 1.23s | Double-check this." in output
    assert "Conversation: conversa" in output
    assert "Classification: INTERNAL (Internal)" in output
    assert "... and 1 more" in output
    assert "TUOCHAT_GITLAB_TOKEN=glpat-ab***" in output
    assert ".env file:" in output
    assert "Doctor:" in output
    assert "Code Interpreter Ready" in output
    assert "mini-racer (V8), lupa" in output
    assert "Preferred Javascript Runtime" in output
    assert "Warnings:" in output


def test_file_listing_and_box_helpers(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "a.py"
    first.write_text("print()", encoding="utf-8")
    monkeypatch.setattr(rendering, "list_include_candidates", lambda: [first])
    monkeypatch.setattr(rendering, "blind_mode_enabled", lambda obj: True)
    monkeypatch.setattr(rendering, "number_label", lambda index, *, blind_mode: f"{index}")

    state = SimpleNamespace(last_candidates=None)
    rendering.print_files(state)
    monkeypatch.setattr(rendering, "list_include_candidates", lambda: [])
    rendering.print_files(state)

    monkeypatch.setattr(rendering, "estimate_tokens", lambda text: 7)
    monkeypatch.setattr(rendering, "word_count", lambda text: 3)
    assert rendering.text_size_lines("hello world") == [
        "tokens(est): 7",
        "words: 3",
        "chars: 11",
        "kilobytes: 0.01",
    ]
    box = rendering.ascii_box("Title", ["line one", "line two"], width=20)
    assert box[0].startswith("+")
    assert box[-1].startswith("+")
    assert rendering.context_preview("hello\n  world", limit=20) == "hello world"
    assert rendering.context_preview("   ") == "(empty)"
    assert rendering.context_preview("x" * 30, limit=10) == "xxxxxxxxxx..."
    assert rendering.context_stats_line("hello", context_window=0).endswith("/ 0 %")
    assert rendering.context_box("Context", "hello", context_window=10)
    assert rendering.remaining_context_box(used_tokens=10, remaining_tokens=90, context_window=100)

    output = capsys.readouterr().out
    assert "Pick a file with /include or /attach N:" in output
    assert "1 a.py" in output
    assert "No include-able files found in the current working directory." in output


def test_print_context_supports_scalar_modes_and_detailed_views(monkeypatch, capsys):
    conv = make_conversation(system_prompt="system prompt")
    conv.messages = [
        Message(role=Role.USER.value, content="personalization request"),
        Message(role=Role.USER.value, content="actual prompt"),
        Message(role=Role.ASSISTANT.value, content="assistant reply"),
    ]
    state = SimpleNamespace(
        conv=conv,
        cfg=SimpleNamespace(chat=SimpleNamespace(context_window_tokens=100)),
        context_view_mode=None,
    )
    monkeypatch.setattr(rendering, "estimate_tokens", lambda text: len(text.split()))
    monkeypatch.setattr(rendering, "word_count", lambda text: len(text.split()))
    monkeypatch.setattr(rendering, "extract_personalization_from_conversation", lambda conv: "personalization")
    monkeypatch.setattr(rendering, "extract_loaded_skills", lambda conv: [("skill-a", "skill body")])
    monkeypatch.setattr(rendering, "extract_used_templates", lambda conv: [("template-a", "template body", {})])
    monkeypatch.setattr(rendering, "context_usage_summary", lambda state: (12, 88))
    monkeypatch.setattr(
        rendering,
        "extract_template_message_metadata",
        lambda message: {"name": "starter"} if message.content == "actual prompt" else None,
    )

    monkeypatch.setattr(rendering, "blind_mode_enabled", lambda state: False)
    state.context_view_mode = "kb"
    rendering.print_context(state)
    state.context_view_mode = "chars"
    rendering.print_context(state)
    state.context_view_mode = "words"
    rendering.print_context(state)
    state.context_view_mode = "tokens"
    rendering.print_context(state)

    state.context_view_mode = None
    rendering.print_context(state)

    monkeypatch.setattr(rendering, "blind_mode_enabled", lambda state: True)
    rendering.print_context(state)

    output = capsys.readouterr().out
    assert "Context kb:" in output
    assert "Context chars:" in output
    assert "Context words:" in output
    assert "Context tokens:" in output
    assert "System Prompt" in output
    assert "Template: template-a" in output
    assert "Prompt #1 (Template: starter)" in output
    assert "Totals: tokens" in output
    assert "Context Remaining" in output


def test_token_chat_attachment_and_saved_file_summaries(monkeypatch, capsys):
    conv = make_conversation(title="Chat")
    conv.messages = [
        Message(role=Role.USER.value, content="hello there"),
        Message(role=Role.ASSISTANT.value, content="general kenobi"),
    ]
    state = SimpleNamespace(
        conv=conv,
        cfg=SimpleNamespace(chat=SimpleNamespace(context_window_tokens=100)),
        last_include_message="included text",
        pending_attachment_messages=["file one", "file two"],
        session_turns=2,
        session_input_tokens=11,
        session_output_tokens=22,
        pending_attachment_names=["one.txt", "two.txt"],
        last_saved_markdown_path=Path("chat.md"),
        last_saved_extracted_count=3,
        last_saved_virtual_file_notice=True,
        active_classification="internal",
    )
    monkeypatch.setattr(rendering, "estimate_tokens", lambda text: len(text.split()))
    monkeypatch.setattr(rendering, "estimate_token_cost", lambda input_tokens, output_tokens: (0.12, 0.34, 0.46))
    monkeypatch.setattr(rendering, "format_cost", lambda value: f"${value:.2f}")
    monkeypatch.setattr(rendering, "word_count", lambda text: len(text.split()))

    rendering.print_token_check(state)
    rendering.print_chat_summary(Conversation(messages=[]))
    rendering.print_chat_summary(conv, state)
    rendering.print_pending_attachments(SimpleNamespace(pending_attachment_names=[]))
    rendering.print_pending_attachments(state)
    rendering.print_attachment_estimate("Attachment estimate", "file one\nfile two", file_count=2)
    rendering.print_saved_conversation_files(SimpleNamespace(last_saved_markdown_path=None))
    rendering.print_saved_conversation_files(state)

    output = capsys.readouterr().out
    assert "Token estimate:" in output
    assert "Pending Attachment Cost: $0.12" in output
    assert "Chat summary: no messages were sent." in output
    assert "Session totals:" in output
    assert "No pending attachments." in output
    assert "[1] one.txt" in output
    assert "Attachment estimate:" in output
    assert "Saved conversation files [INTERNAL (Internal)]: chat.md (3 extracted file(s))" in output
    assert "Named files written to central archive (write-here mode is off)." in output


def test_print_context_shows_pending_attachments_in_single_box(capsys):
    conv = make_conversation(title="Chat", system_prompt="System prompt")
    conv.messages = [
        Message(role=Role.USER.value, content="hello"),
        Message(role=Role.ASSISTANT.value, content="hi"),
    ]
    state = SimpleNamespace(
        conv=conv,
        cfg=SimpleNamespace(chat=SimpleNamespace(context_window_tokens=100)),
        pending_attachment_names=["one.txt", "[template] bundled:recipe.md"],
        pending_attachment_messages=["file one", "template payload"],
        context_view_mode="brief",
    )

    rendering.print_context(state)

    output = capsys.readouterr().out
    assert "Pending Attachments" in output
    assert "[1] one.txt" in output
    assert "[2] [template] bundled:recipe.md" in output
