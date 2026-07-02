"""Focused tests for minimal Tkinter GUI helpers."""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter", exc_type=ImportError)

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuochat.cli.models import ReplState
from tuochat.config import TuochatConfig
from tuochat.context.artifacts import ArtifactKind, ContextArtifact
from tuochat.context.recipes import Recipe, RecipeMatch
from tuochat.discovery.skills import render_skill_message
from tuochat.discovery.templates import render_template_prompt_from_path
from tuochat.gui.context_browser import ContextBrowserTab
from tuochat.gui.dialogs import DialogCancelledError, PromptRequest, prompt_for_template_code_path
from tuochat.gui.rendering import (
    about_dialog_text,
    attached_files_dialog_text,
    attachment_speedbar_labels,
    classification_dialog_text,
    configured_gui_model,
    confirm_nuke,
    conversation_menu_label,
    default_export_filename,
    format_info_line,
    format_sandbox_runtime_summary,
    format_token_usage,
    format_writing_directory_line,
    is_attached_code_prompt,
    is_classification_prompt,
    keyboard_shortcuts_text,
    next_model_key,
    next_model_toggle_label,
    render_attached_files_text,
    render_context_text,
    render_conversation_markdown,
    render_conversations_text,
    render_help_text,
    render_search_results_text,
    render_weekly_usage_text,
    response_warning_text,
    submit_shortcut_sequences,
    theme_colors,
    window_title_text,
)
from tuochat.gui.streams import MultiTextIO, TranscriptStream
from tuochat.models import Conversation, ConversationSearchResult, Message, Role


class FakeButton:
    def __init__(self) -> None:
        self.state = None

    def configure(self, *, state: str) -> None:
        self.state = state


def test_attachment_speedbar_labels_compact_attach_controls():
    assert attachment_speedbar_labels() == (
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


def test_about_dialog_text_includes_version_author_and_legalese():
    text = about_dialog_text()

    assert text.startswith("Tuochat")
    assert "Version:" in text
    assert "Matthew Dean Martin" in text
    assert "Tuochat is about 99% written by ChatGPT, Codex, Copilot, Gemini, Claude Code." in text


def test_conversation_menu_label_marks_current_conversation():
    conv = Conversation(
        id="conversation-1234",
        title="A very useful saved conversation title",
        updated_at="2026-04-03T21:00:00+00:00",
    )

    label = conversation_menu_label(conv, current_id="conversation-1234")

    assert label.startswith("* ")
    assert "A very useful saved conversation title" in label
    assert "ago" in label


def test_default_export_filename_sanitizes_title():
    conv = Conversation(id="conv-1", title='Plan: alpha/beta?*"<>')

    assert default_export_filename(conv) == "Plan- alpha-beta.md"


def test_render_conversation_markdown_uses_in_memory_messages():
    conv = Conversation(
        id="conv-1",
        title="Export me",
        system_prompt="Be helpful.",
        created_at="2026-04-03T20:00:00+00:00",
        messages=[
            Message(role=Role.USER.value, content="Hello"),
            Message(role=Role.ASSISTANT.value, content="Hi there"),
        ],
    )

    markdown = render_conversation_markdown(conv)

    assert "# Export me" in markdown
    assert "**System prompt:** Be helpful." in markdown
    assert "## User" in markdown
    assert "## Assistant" in markdown
    assert "Hi there" in markdown


def test_confirm_nuke_requires_both_confirmation_steps():
    yes_no_prompts: list[tuple[str, str]] = []
    text_prompts: list[tuple[str, str]] = []

    result = confirm_nuke(
        ask_yes_no=lambda title, prompt: yes_no_prompts.append((title, prompt)) or True,
        ask_text=lambda title, prompt: text_prompts.append((title, prompt)) or "NUKE",
    )

    assert result is True
    assert yes_no_prompts == [
        (
            "Confirm nuke",
            "Delete centralized app data and close tuochat?\n\nThis keeps the config folder and current workspace.",
        )
    ]
    assert text_prompts == [("Confirm nuke", "Type `nuke` to confirm data deletion:")]


def test_classification_dialog_text_lists_choices_and_instruction():
    cfg = TuochatConfig()
    cfg.classification.markings = ["SECRET", "PUBLIC"]

    text = classification_dialog_text(cfg, current="SECRET")

    assert "Enter a picker number or the exact classification text." in text
    assert "[1] Classification pending review" in text
    assert "Secret" in text
    assert "* current" in text


def test_format_token_usage_humanizes_totals():
    assert format_token_usage(1_234, 56_789) == "Token usage: in 1,234 | out 56,789 | total 58,023"


def test_format_info_line_compacts_session_details():
    line = format_info_line(
        input_tokens=1_234,
        output_tokens=56_789,
        active_model="duo",
        working_directory=Path("C:\\repo"),
        classification="SECRET",
        elapsed_seconds=0.38,
    )

    assert line.startswith("Elapsed: 0.38s | ")
    assert "Token usage: in 1,234 | out 56,789 | total 58,023" in line
    assert "Model: Duo" in line
    assert "Cwd: C:\\repo" in line
    assert "Classification: Secret" in line


def test_format_info_line_includes_sandbox_runtime_summary():
    line = format_info_line(
        input_tokens=10,
        output_tokens=20,
        active_model="duo",
        working_directory=Path("C:\\repo"),
        classification=None,
        elapsed_seconds=None,
        sandbox_runtime_summary="mini-racer/V8 yes | lupa no",
    )

    assert "Sandbox: mini-racer/V8 yes | lupa no" in line


def test_format_sandbox_runtime_summary_compacts_runtime_flags():
    summary = format_sandbox_runtime_summary({"mini_racer_v8": True, "lupa": False})

    assert summary == "mini-racer/V8 yes | lupa no"


def test_format_writing_directory_line_keeps_path_on_second_row():
    assert format_writing_directory_line("C:\\repo\\writes") == "Writing dir: C:\\repo\\writes"


def test_response_warning_text_uses_config_toggle():
    cfg = TuochatConfig()
    cfg.chat.response_footer_warning_enabled = True
    cfg.chat.response_footer_warning_text = "Responses may be inaccurate. Verify before use."

    assert response_warning_text(cfg) == "Responses may be inaccurate. Verify before use."

    cfg.chat.response_footer_warning_enabled = False
    assert response_warning_text(cfg) == ""


def test_next_model_toggle_cycles_through_all_providers():
    assert next_model_key("duo") == "eliza"
    assert next_model_key("eliza") == "openrouter"
    assert next_model_key("openrouter") == "duo"
    assert next_model_key("unknown") == "duo"

    assert next_model_toggle_label("duo") == "Use Eliza"
    assert next_model_toggle_label("eliza") == "Use OpenRouter"
    assert next_model_toggle_label("openrouter") == "Use Duo"


def test_configured_gui_model_prefers_duo_when_both_are_available():
    cfg = TuochatConfig()
    cfg.gitlab.host = "https://gitlab.example.com"
    cfg.gitlab.token = "glpat-test"
    cfg.openrouter.api_key = "sk-or-test"
    cfg.openrouter.model = "openai/gpt-4.1-mini"

    assert configured_gui_model(cfg) == "duo"


def test_configured_gui_model_supports_openrouter_only_configuration():
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-or-test"
    cfg.openrouter.model = "openai/gpt-4.1-mini"

    assert configured_gui_model(cfg) == "openrouter"


def test_configured_gui_model_requires_openrouter_key_and_model():
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-or-test"

    assert configured_gui_model(cfg) is None


def test_window_title_text_uses_conversation_title_when_present():
    assert window_title_text(None) == "Tuochat"
    assert window_title_text("  Sprint review  ") == "Tuochat: Sprint review"


def test_render_attached_files_text_lists_pending_and_last_include():
    state = ReplState(
        conv=Conversation(),
        store=None,
        provider=None,
        cfg=TuochatConfig(),
        streaming=True,
        include_agents_file=True,
        pending_custom_name="bundled:security.md",
        pending_attachment_names=["C:\\repo\\notes.txt", "C:\\repo\\plan.md"],
        last_include_path=Path("C:\\repo\\notes.txt"),
        last_include_size=1234,
    )

    rendered = render_attached_files_text(state)

    assert "Agent prompt:" in rendered
    assert "Pending custom instructions for next new conversation: bundled:security.md" in rendered
    assert "Pending attachments (2):" in rendered
    assert "[1]" in rendered and "notes.txt" in rendered
    assert "Last include size: 1,234 bytes" in rendered


def test_render_context_text_includes_pending_attachments_for_next_turn():
    state = ReplState(
        conv=Conversation(),
        store=None,
        provider=None,
        cfg=TuochatConfig(),
        streaming=True,
        pending_attachment_names=["[sandbox]"],
        pending_attachment_messages=["Sandbox execution result:\nstdout:\n```\n42\n```"],
    )

    rendered = render_context_text(state)

    assert "Pending Attachments" in rendered
    assert "[1] [sandbox]" in rendered


def test_attached_files_dialog_text_lists_selected_paths():
    text = attached_files_dialog_text([Path("C:\\repo\\notes.txt"), Path("C:\\repo\\plan.md")])

    assert text.startswith("Attached these files for the next request.")
    assert "[1] C:\\repo\\notes.txt" in text
    assert "[2] C:\\repo\\plan.md" in text


def test_render_conversations_text_marks_current_conversation():
    conversations = [
        Conversation(
            id="conversation-1234",
            title="Current conversation",
            updated_at="2026-04-03T21:00:00+00:00",
        ),
        Conversation(
            id="conversation-5678",
            title="Older conversation",
            updated_at="2026-04-03T20:00:00+00:00",
        ),
    ]

    rendered = render_conversations_text(conversations, current_id="conversation-1234")

    assert rendered.startswith("Recent conversations (read-only for now):")
    assert "[1] * Current conversation" in rendered
    assert "Older conversation" in rendered


def test_render_search_results_text_formats_matches():
    rendered = render_search_results_text(
        [
            ConversationSearchResult(
                conversation_id="conversation-1234",
                message_id="message-1",
                role="assistant",
                title="Searchable conversation",
                updated_at="2026-04-03T21:00:00+00:00",
                snippet="first line\nsecond line",
            )
        ],
        query="search term",
    )

    assert "Search results for 'search term':" in rendered
    assert "[1] conversa  Searchable conversation" in rendered
    assert "first line second line" in rendered


def test_render_help_text_renders_help_section_without_prompting():
    rendered = render_help_text("/help files")

    assert "Attachments and Context:" in rendered
    assert "/include, /attach [path|n]" in rendered


def test_render_template_prompt_from_path_uses_auto_values_and_prompted_vars(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template_path = tmp_path / "explain" / "TEMPLATE.md"
    template_path.parent.mkdir(parents=True)
    template_path.write_text(
        "---\nname: explain\ndescription: Explain helper\n---\nTask: {TASK}\nDate: {DATE}\n",
        encoding="utf-8",
    )

    label, rendered_prompt, metadata = render_template_prompt_from_path(
        template_path,
        SimpleNamespace(templates_dir=tmp_path / "central-templates"),
        prompt_for_value=lambda variable: "summarize the parser" if variable == "TASK" else "",
        cwd=tmp_path,
    )

    assert label == "cwd:explain (explain)"
    assert "Task: summarize the parser" in rendered_prompt
    assert "Date:" in rendered_prompt
    assert metadata["label"] == "cwd:explain (explain)"
    assert metadata["name"] == "explain"
    assert metadata["variables"] == {"TASK": "summarize the parser"}
    assert metadata["auto_variables"] == ["DATE"]


def test_render_skill_message_expands_neighbor_placeholders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill_path = tmp_path / "sandbox-helper" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("Rules:\n{javascript}", encoding="utf-8")
    (skill_path.parent / "javascript.md").write_text("Use the JavaScript sandbox.", encoding="utf-8")

    label, payload = render_skill_message(skill_path, SimpleNamespace(skills_dir=tmp_path / "central-skills"))

    assert label == "cwd:sandbox-helper (sandbox-helper)"
    assert "Loaded skill: cwd:sandbox-helper (sandbox-helper)" in payload
    assert "Use the JavaScript sandbox." in payload
    assert "{javascript}" not in payload


def test_render_weekly_usage_text_formats_store_totals():
    class FakeStore:
        def get_weekly_usage(self, week_start_iso: str) -> dict:
            assert len(week_start_iso) >= 10
            return {"input_tokens": 1000, "output_tokens": 250, "total_tokens": 1250, "turns": 4}

    rendered = render_weekly_usage_text(FakeStore())

    assert rendered.startswith("Weekly usage (since ")
    assert "Turns: 4" in rendered
    assert "Input Tokens: 1,000" in rendered
    assert "Approximate Kilobytes:" in rendered
    assert "Total Cost:" in rendered


def test_submit_shortcut_sequences_include_alt_s():
    assert submit_shortcut_sequences() == ("<Alt-s>", "<Alt-S>")


def test_is_classification_prompt_matches_cli_picker_prompt():
    assert is_classification_prompt("classify> ")
    assert not is_classification_prompt("resource id: ")


def test_is_attached_code_prompt_matches_template_file_request():
    assert is_attached_code_prompt("Attached code file: ")
    assert is_attached_code_prompt(" attached CODE file ")
    assert not is_attached_code_prompt("Attached code: ")


def test_prompt_for_template_code_path_uses_file_dialog(monkeypatch, tmp_path):
    code_path = tmp_path / "sample.py"
    code_path.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr("tuochat.gui.app.filedialog.askopenfilename", lambda **kwargs: str(code_path))

    assert prompt_for_template_code_path(None, initialdir=tmp_path) == str(code_path)


def test_context_browser_update_action_buttons_respects_artifact_kind():
    tab = ContextBrowserTab.__new__(ContextBrowserTab)
    tab.btn_attach_request = FakeButton()
    tab.btn_attach_conversation = FakeButton()
    tab.btn_set_agent = FakeButton()
    tab.btn_copy_path = FakeButton()
    tab.btn_open_editor = FakeButton()

    file_artifact = ContextArtifact(
        kind=ArtifactKind.FILE_ATTACHMENT,
        display_name="notes.txt",
        source_label="cwd:notes.txt",
        path=Path("C:\\repo\\notes.txt"),
    )
    ContextBrowserTab.update_action_buttons(tab, file_artifact)
    assert tab.btn_attach_request.state == "normal"
    assert tab.btn_attach_conversation.state == "disabled"
    assert tab.btn_set_agent.state == "disabled"
    assert tab.btn_copy_path.state == "normal"

    agent_artifact = ContextArtifact(
        kind=ArtifactKind.AGENT_PROMPT,
        display_name="AGENTS.md",
        source_label="cwd:AGENTS.md",
        path=Path("C:\\repo\\AGENTS.md"),
    )
    ContextBrowserTab.update_action_buttons(tab, agent_artifact)
    assert tab.btn_attach_request.state == "disabled"
    assert tab.btn_set_agent.state == "normal"

    custom_artifact = ContextArtifact(
        kind=ArtifactKind.CUSTOM_INSTRUCTION,
        display_name="custom.md",
        source_label="cwd:custom.md",
    )
    ContextBrowserTab.update_action_buttons(tab, custom_artifact)
    assert tab.btn_attach_request.state == "disabled"
    assert tab.btn_attach_conversation.state == "normal"

    recipe = Recipe(name="demo", display_name="Demo Recipe", description="test", globs=["*.txt"])
    ContextBrowserTab.update_action_buttons(tab, None, recipe=recipe)
    assert tab.btn_attach_request.state == "normal"
    assert tab.btn_copy_path.state == "disabled"


def test_context_browser_do_attach_recipe_builds_recipe_payload():
    attached: list[tuple[str, str, str]] = []
    tab = ContextBrowserTab.__new__(ContextBrowserTab)
    tab.on_attach_next_request = lambda label, payload, kind: attached.append((label, payload, kind))

    recipe = Recipe(name="demo", display_name="Demo Recipe", description="test", globs=["*.txt"])
    match = RecipeMatch(
        recipe=recipe,
        matched_paths=[Path("C:\\repo\\notes.txt")],
        skipped_paths=[],
        rendered="# notes.txt\n```txt\nhello\n```",
        estimated_tokens=42,
    )

    ContextBrowserTab.do_attach_recipe(tab, match)

    assert attached == [
        (
            "Demo Recipe",
            "Recipe attachment: Demo Recipe\n(1 files, ~42 tokens)\n\n# notes.txt\n```txt\nhello\n```",
            "recipe",
        )
    ]


def test_context_browser_attach_recipe_shows_info_for_empty_match(monkeypatch):
    tab = ContextBrowserTab.__new__(ContextBrowserTab)
    tab.parent = object()
    tab.on_attach_next_request = lambda *args: None

    recipe = Recipe(name="demo", display_name="Demo Recipe", description="test", globs=["*.txt"])
    empty_match = RecipeMatch(recipe=recipe, matched_paths=[], skipped_paths=[], rendered="", estimated_tokens=0)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr("tuochat.gui.context_browser.expand_recipe", lambda recipe: empty_match)
    monkeypatch.setattr(
        "tuochat.gui.context_browser.messagebox.showinfo",
        lambda title, message, parent=None: calls.append((title, message)),
    )

    ContextBrowserTab.attach_recipe(tab, recipe)

    assert calls == [("Context Browser", "Recipe 'Demo Recipe' matched no files in the current directory.")]


def test_context_browser_attach_recipe_routes_large_matches_to_preview(monkeypatch):
    tab = ContextBrowserTab.__new__(ContextBrowserTab)
    tab.parent = object()
    tab.on_attach_next_request = lambda *args: None

    recipe = Recipe(name="demo", display_name="Demo Recipe", description="test", globs=["*.txt"])
    large_match = RecipeMatch(
        recipe=recipe,
        matched_paths=[Path("C:\\repo\\notes.txt")] * 31,
        skipped_paths=[],
        rendered="payload",
        estimated_tokens=100,
    )
    previewed: list[RecipeMatch] = []
    attached: list[RecipeMatch] = []

    monkeypatch.setattr("tuochat.gui.context_browser.expand_recipe", lambda recipe: large_match)
    tab.show_recipe_attach_dialog = previewed.append
    tab.do_attach_recipe = attached.append

    ContextBrowserTab.attach_recipe(tab, recipe)

    assert previewed == [large_match]
    assert attached == []


# ---------------------------------------------------------------------------
# theme_colors
# ---------------------------------------------------------------------------


def test_theme_colors_returns_five_tuple_for_known_themes():
    for theme in ("light", "dark", "green_terminal", "amber_terminal", "solarized", "hot_dog_stand"):
        result = theme_colors(theme)
        assert result is not None, f"expected colors for {theme!r}"
        assert len(result) == 5
        for value in result:
            assert isinstance(value, str) and value.startswith("#"), f"bad color {value!r} in {theme!r}"


def test_theme_colors_returns_none_for_unknown_theme():
    assert theme_colors("nonexistent") is None
    assert theme_colors("") is None
    assert theme_colors("system") is None


# ---------------------------------------------------------------------------
# keyboard_shortcuts_text
# ---------------------------------------------------------------------------


def test_keyboard_shortcuts_text_covers_submit_navigation_and_editing():
    text = keyboard_shortcuts_text()
    assert "Alt+S" in text
    assert "Ctrl+Z" in text
    assert "Alt+H" in text
    assert "Alt+Q" in text
    assert "Up arrow" in text
    assert "Ctrl+A" in text


# ---------------------------------------------------------------------------
# confirm_nuke edge cases
# ---------------------------------------------------------------------------


def test_confirm_nuke_returns_false_when_first_step_declined():
    result = confirm_nuke(
        ask_yes_no=lambda title, prompt: False,
        ask_text=lambda title, prompt: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    assert result is False


def test_confirm_nuke_returns_false_when_wrong_text_typed():
    result = confirm_nuke(
        ask_yes_no=lambda title, prompt: True,
        ask_text=lambda title, prompt: "delete",
    )
    assert result is False


def test_confirm_nuke_returns_false_when_text_dialog_cancelled():
    result = confirm_nuke(
        ask_yes_no=lambda title, prompt: True,
        ask_text=lambda title, prompt: None,
    )
    assert result is False


def test_confirm_nuke_accepts_nuke_with_surrounding_whitespace():
    result = confirm_nuke(
        ask_yes_no=lambda title, prompt: True,
        ask_text=lambda title, prompt: "  NUKE  ",
    )
    assert result is True


# ---------------------------------------------------------------------------
# default_export_filename edge cases
# ---------------------------------------------------------------------------


def test_default_export_filename_falls_back_to_conversation_when_title_empty():
    conv = Conversation(id="abc12345", title="")
    assert default_export_filename(conv) == "abc12345.md"


def test_default_export_filename_falls_back_to_conversation_literal_when_all_special():
    conv = Conversation(id="", title="???")
    assert default_export_filename(conv) == "conversation.md"


def test_default_export_filename_preserves_spaces_and_dots():
    conv = Conversation(id="x", title="my notes v1.2")
    assert default_export_filename(conv) == "my notes v1.2.md"


# ---------------------------------------------------------------------------
# render_conversation_markdown with explicit message override
# ---------------------------------------------------------------------------


def test_render_conversation_markdown_with_message_override():
    conv = Conversation(
        id="conv-1",
        title="Override test",
        messages=[Message(role=Role.USER.value, content="original")],
    )
    override = [Message(role=Role.ASSISTANT.value, content="overridden reply")]

    markdown = render_conversation_markdown(conv, messages=override)

    assert "overridden reply" in markdown
    assert "original" not in markdown


def test_render_conversation_markdown_untitled_fallback():
    conv = Conversation(id="conv-1", title="")
    markdown = render_conversation_markdown(conv)
    assert "# Untitled Conversation" in markdown


# ---------------------------------------------------------------------------
# render_conversations_text edge cases
# ---------------------------------------------------------------------------


def test_render_conversations_text_empty_list():
    assert render_conversations_text([]) == "No saved conversations yet."


def test_render_conversations_text_unavailable():
    rendered = render_conversations_text([], unavailable=True)
    assert "no-write mode" in rendered


def test_render_conversations_text_no_current_id():
    convs = [Conversation(id="conversation-1234", title="Solo", updated_at="2026-01-01T00:00:00+00:00")]
    rendered = render_conversations_text(convs, current_id=None)
    assert "* " not in rendered
    assert "Solo" in rendered


# ---------------------------------------------------------------------------
# render_search_results_text edge cases
# ---------------------------------------------------------------------------


def test_render_search_results_text_no_results_with_query():
    rendered = render_search_results_text([], query="foobar")
    assert "foobar" in rendered
    assert "No saved conversations" in rendered


def test_render_search_results_text_no_results_no_query():
    rendered = render_search_results_text(None)
    assert "No search results yet" in rendered


def test_render_search_results_text_no_query_header():
    result = ConversationSearchResult(
        conversation_id="conv-abc12345",
        message_id="msg-1",
        role="user",
        title="Untitled",
        updated_at="2026-01-01T00:00:00+00:00",
        snippet="hello world",
    )
    rendered = render_search_results_text([result])
    assert rendered.startswith("Search results:")


def test_render_search_results_text_collapses_whitespace_in_snippet():
    result = ConversationSearchResult(
        conversation_id="conv-abc12345",
        message_id="msg-1",
        role="user",
        title="Whitespace test",
        updated_at="2026-01-01T00:00:00+00:00",
        snippet="line one\n   line two\t\tline three",
    )
    rendered = render_search_results_text([result], query="test")
    assert "line one line two line three" in rendered


# ---------------------------------------------------------------------------
# render_attached_files_text — kind hint labels
# ---------------------------------------------------------------------------


def test_render_attached_files_text_shows_skill_and_template_kind_hints():
    state = ReplState(
        conv=Conversation(),
        store=None,
        provider=None,
        cfg=TuochatConfig(),
        streaming=True,
        pending_attachment_names=["[skill] my-skill", "[template] my-template", "[recipe] my-recipe"],
        pending_attachment_messages=[],
    )

    rendered = render_attached_files_text(state)

    assert "[skill]" in rendered
    assert "[template]" in rendered
    assert "[recipe]" in rendered


def test_render_attached_files_text_no_attachments_message():
    state = ReplState(
        conv=Conversation(),
        store=None,
        provider=None,
        cfg=TuochatConfig(),
        streaming=True,
    )

    rendered = render_attached_files_text(state)

    assert "No attachments are currently queued." in rendered


def test_render_attached_files_text_excluded_agent_prompt():
    state = ReplState(
        conv=Conversation(),
        store=None,
        provider=None,
        cfg=TuochatConfig(),
        streaming=True,
        include_agents_file=False,
    )

    rendered = render_attached_files_text(state)

    assert "Agent prompt: excluded" in rendered


# ---------------------------------------------------------------------------
# render_help_text — blind_mode and /help-menu
# ---------------------------------------------------------------------------


def test_render_help_text_blind_mode_emits_menu():
    rendered = render_help_text("/help", blind_mode=True)
    assert len(rendered) > 0
    assert "Help is unavailable." not in rendered


def test_render_help_text_help_menu_command():
    rendered = render_help_text("/help-menu")
    assert len(rendered) > 0


def test_render_help_text_unknown_topic_prints_usage():
    rendered = render_help_text("/help bogus_topic_xyz")
    assert "Usage:" in rendered


# ---------------------------------------------------------------------------
# classification_dialog_text — upcoming flag
# ---------------------------------------------------------------------------


def test_classification_dialog_text_upcoming_label():
    cfg = TuochatConfig()
    text = classification_dialog_text(cfg, upcoming=True)
    assert "upcoming conversation" in text


def test_classification_dialog_text_no_current_marker_when_unset():
    cfg = TuochatConfig()
    cfg.classification.markings = ["PUBLIC", "SECRET"]
    text = classification_dialog_text(cfg, current=None)
    assert "* current" not in text


# ---------------------------------------------------------------------------
# conversation_menu_label edge cases
# ---------------------------------------------------------------------------


def test_conversation_menu_label_no_current_id():
    conv = Conversation(id="conversation-abcd", title="My chat", updated_at="2026-03-01T10:00:00+00:00")
    label = conversation_menu_label(conv)
    assert not label.startswith("* ")
    assert "My chat" in label


def test_conversation_menu_label_truncates_long_title():
    conv = Conversation(id="conversation-abcd", title="A" * 80, updated_at="2026-03-01T10:00:00+00:00")
    label = conversation_menu_label(conv)
    assert "A" * 41 not in label


def test_conversation_menu_label_no_updated_at():
    conv = Conversation(id="conversation-abcd", title="No date", updated_at=None)
    label = conversation_menu_label(conv)
    assert "No date" in label


# ---------------------------------------------------------------------------
# PromptRequest dataclass
# ---------------------------------------------------------------------------


def test_prompt_request_defaults():
    import threading

    req = PromptRequest(prompt="Password: ", secret=True)
    assert req.prompt == "Password: "
    assert req.secret is True
    assert req.response == ""
    assert isinstance(req.ready, threading.Event)
    assert not req.ready.is_set()


def test_prompt_request_ready_event_can_be_set():
    req = PromptRequest(prompt="Enter value: ")
    req.response = "hello"
    req.ready.set()
    assert req.ready.is_set()


# ---------------------------------------------------------------------------
# DialogCancelledError
# ---------------------------------------------------------------------------


def test_dialog_cancelled_error_is_exception():
    with pytest.raises(DialogCancelledError):
        raise DialogCancelledError("user cancelled")


# ---------------------------------------------------------------------------
# TranscriptStream
# ---------------------------------------------------------------------------


def test_transcript_stream_write_enqueues_text():
    import queue

    q: queue.Queue[str] = queue.Queue()
    stream = TranscriptStream(q)
    n = stream.write("hello")
    assert n == 5
    assert q.get_nowait() == "hello"


def test_transcript_stream_skips_empty_writes():
    import queue

    q: queue.Queue[str] = queue.Queue()
    stream = TranscriptStream(q)
    stream.write("")
    assert q.empty()


def test_transcript_stream_is_writable():
    import queue

    stream = TranscriptStream(queue.Queue())
    assert stream.writable() is True


# ---------------------------------------------------------------------------
# MultiTextIO
# ---------------------------------------------------------------------------


def test_multi_text_io_broadcasts_to_all_streams():
    import io

    a = io.StringIO()
    b = io.StringIO()
    multi = MultiTextIO(a, b)
    n = multi.write("ping")
    assert n == 4
    assert a.getvalue() == "ping"
    assert b.getvalue() == "ping"


def test_multi_text_io_flush_calls_all_streams():
    flushed: list[str] = []

    class FakeStream(io.StringIO):
        def flush(self):
            flushed.append("flushed")

    a = FakeStream()
    b = FakeStream()
    multi = MultiTextIO(a, b)
    multi.flush()
    assert flushed == ["flushed", "flushed"]


def test_multi_text_io_is_writable():
    multi = MultiTextIO()
    assert multi.writable() is True
