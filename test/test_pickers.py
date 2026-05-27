"""Unit tests for CLI picker helpers."""

from __future__ import annotations

from types import SimpleNamespace

from tuochat.cli import pickers
from tuochat.config import TuochatConfig
from tuochat.models import Conversation, ConversationSearchResult


class ConversationStoreStub:
    """Minimal conversation store for picker tests."""

    def __init__(
        self,
        *,
        conversations: list[Conversation] | None = None,
        archived: list[Conversation] | None = None,
        matches: list[ConversationSearchResult] | None = None,
    ):
        self.conversations = list(conversations or [])
        self.archived = list(archived or [])
        self.matches = list(matches or [])

    def list_conversations(self, limit: int) -> list[Conversation]:
        return list(self.conversations[:limit])

    def list_archived_conversations(self, limit: int) -> list[Conversation]:
        return list(self.archived[:limit])

    def search_conversations(
        self,
        query: str,
        *,
        limit: int,
        title_filter: str | None,
        updated_after: str | None,
        updated_before: str | None,
    ) -> list[ConversationSearchResult]:
        self.last_search = (query, limit, title_filter, updated_after, updated_before)
        return list(self.matches[:limit])


def test_print_picker_lists_relative_paths_and_empty_state(capsys, tmp_path):
    root = tmp_path
    path = root / "nested" / "file.txt"
    path.parent.mkdir()
    path.write_text("x", encoding="utf-8")

    pickers.print_picker([], root, "template", "/template")
    assert f"No template files found in {root}." in capsys.readouterr().out

    pickers.print_picker([path], root, "template", "/template")
    output = capsys.readouterr().out
    assert "Pick a template file with /template N:" in output
    assert "[1] nested" in output


def test_specialized_pickers_render_described_entries(monkeypatch, capsys, tmp_path):
    cfg = TuochatConfig()
    candidate = tmp_path / "item.md"
    candidate.write_text("x", encoding="utf-8")

    monkeypatch.setattr(pickers, "blind_mode_enabled", lambda obj: True)
    monkeypatch.setattr(pickers, "number_label", lambda index, *, blind_mode: f"#{index}:{blind_mode}")
    monkeypatch.setattr(pickers, "describe_skill_path", lambda path, cfg: f"skill:{path.name}")
    monkeypatch.setattr(pickers, "describe_template_path", lambda path, cfg: f"template:{path.name}")
    monkeypatch.setattr(pickers, "describe_custom_instruction_path", lambda path, cfg: f"custom:{path.name}")

    pickers.print_skill_picker([candidate], cfg)
    pickers.print_template_picker([candidate], cfg)
    pickers.print_custom_instruction_picker([candidate], cfg)

    output = capsys.readouterr().out
    assert "Pick a skill file with /skill N:" in output
    assert "Pick a template file with /template N:" in output
    assert "Pick a custom instruction file with /custom N:" in output
    assert "#1:True skill:item.md" in output
    assert "#1:True template:item.md" in output
    assert "#1:True custom:item.md" in output


def test_specialized_pickers_report_no_candidates(capsys):
    cfg = TuochatConfig()

    pickers.print_skill_picker([], cfg)
    pickers.print_template_picker([], cfg)
    pickers.print_custom_instruction_picker([], cfg)

    output = capsys.readouterr().out
    assert "No skill files found." in output
    assert "No template files found." in output
    assert "No custom instruction files found." in output


def test_resume_and_archived_candidate_lists_update_state(monkeypatch, capsys):
    conversations = [
        Conversation(id="resume-12345678", title="R" * 80, updated_at="2025-01-02T03:04:05+00:00"),
    ]
    archived = [
        Conversation(id="archive-12345678", title=None, updated_at=None),
    ]
    state = SimpleNamespace(
        store=ConversationStoreStub(conversations=conversations, archived=archived),
        resume_candidates=None,
    )
    monkeypatch.setattr(pickers, "blind_mode_enabled", lambda obj: False)
    monkeypatch.setattr(pickers, "number_label", lambda index, *, blind_mode: f"[{index}]")

    pickers.print_resume_candidates(state, limit=5)
    pickers.print_archived_candidates(state, limit=5)

    output = capsys.readouterr().out
    assert "Pick a conversation with /resume N:" in output
    assert "resume-1" in output
    assert "RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR" in output
    assert "Pick an archived conversation with /unarchive N:" in output
    assert "archive-" in output
    assert state.resume_candidates == archived


def test_resume_and_search_printers_report_empty_lists(capsys):
    state = SimpleNamespace(store=ConversationStoreStub(), resume_candidates=None, search_candidates=None)

    pickers.print_resume_candidates(state)
    pickers.print_archived_candidates(state)
    pickers.print_search_candidates(state, "query")

    output = capsys.readouterr().out
    assert "No saved conversations found." in output
    assert "No archived conversations found." in output
    assert "No saved conversations matched 'query'." in output


def test_run_conversation_search_forwards_all_filters():
    store = ConversationStoreStub(matches=[])

    pickers.run_conversation_search(
        store,
        "deploy",
        limit=7,
        title_filter="prod",
        updated_after="2025-01-01",
        updated_before="2025-01-31",
    )

    assert store.last_search == ("deploy", 7, "prod", "2025-01-01", "2025-01-31")


def test_print_search_candidates_formats_matches(monkeypatch, capsys):
    match = ConversationSearchResult(
        conversation_id="conversation-123456",
        message_id="message-1",
        role="assistant-long-role",
        title="T" * 60,
        updated_at="2025-01-02T03:04:05+00:00",
        snippet="hello\n   world",
    )
    state = SimpleNamespace(
        store=ConversationStoreStub(matches=[match]),
        search_candidates=None,
    )
    monkeypatch.setattr(pickers, "blind_mode_enabled", lambda obj: True)
    monkeypatch.setattr(pickers, "number_label", lambda index, *, blind_mode: f"{index}")

    pickers.print_search_candidates(state, "hello", limit=3)

    output = capsys.readouterr().out
    assert "Search results for 'hello':" in output
    assert "1 conversa" in output
    assert "assistant" in output
    assert "hello world" in output
    assert state.search_candidates == [match]


def test_resolve_picker_path_supports_index_lookup_and_validates_bounds(monkeypatch, capsys, tmp_path):
    candidates = [tmp_path / "one.txt", tmp_path / "two.txt"]
    monkeypatch.setattr(pickers, "list_text_files", lambda root: candidates)

    assert pickers.resolve_picker_path("2", root=tmp_path, candidates=None) == candidates[1]
    assert pickers.resolve_picker_path("3", root=tmp_path, candidates=candidates) is None
    assert "Selection out of range." in capsys.readouterr().err


def test_resolve_picker_path_rejects_outside_root(tmp_path, capsys):
    outside = tmp_path.parent / "outside.txt"

    assert pickers.resolve_picker_path(str(outside), root=tmp_path, candidates=None) is None
    assert "Path is outside the working directory" in capsys.readouterr().err


def test_resolve_picker_path_returns_relative_path_inside_root(tmp_path):
    inside = tmp_path / "nested" / "file.txt"
    inside.parent.mkdir()
    inside.write_text("x", encoding="utf-8")

    assert pickers.resolve_picker_path("nested\\file.txt", root=tmp_path, candidates=None) == inside


def test_resolve_skill_path_matches_workspace_file_and_aliases(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    cfg = TuochatConfig(config_dir=tmp_path / "config")
    skill_path = cfg.skills_dir / "alpha" / "skill.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("skill", encoding="utf-8")
    local_file = workspace / "local.md"
    local_file.write_text("local", encoding="utf-8")

    monkeypatch.setattr(pickers, "describe_skill_path", lambda path, cfg: "described-skill")
    monkeypatch.setattr(pickers, "bundled_skills_dir", lambda: tmp_path / "bundled-skills")

    assert pickers.resolve_skill_path("local.md", cfg=cfg, candidates=[skill_path]) == local_file
    assert pickers.resolve_skill_path("alpha", cfg=cfg, candidates=[skill_path]) == skill_path
    assert pickers.resolve_skill_path("described-skill", cfg=cfg, candidates=[skill_path]) == skill_path


def test_resolve_custom_instruction_path_matches_aliases(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    cfg = TuochatConfig(config_dir=tmp_path / "config")
    custom_path = cfg.custom_instructions_dir / "team.md"
    custom_path.parent.mkdir(parents=True)
    custom_path.write_text("custom", encoding="utf-8")

    monkeypatch.setattr(pickers, "describe_custom_instruction_path", lambda path, cfg: "described-custom")
    monkeypatch.setattr(pickers, "bundled_custom_instructions_dir", lambda: tmp_path / "bundled-custom")

    assert pickers.resolve_custom_instruction_path("team.md", cfg=cfg, candidates=[custom_path]) == custom_path
    assert pickers.resolve_custom_instruction_path("described-custom", cfg=cfg, candidates=[custom_path]) == custom_path


def test_resolve_template_path_matches_aliases(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    cfg = TuochatConfig(config_dir=tmp_path / "config")
    template_path = cfg.templates_dir / "starter" / "template.md"
    template_path.parent.mkdir(parents=True)
    template_path.write_text("template", encoding="utf-8")

    monkeypatch.setattr(pickers, "describe_template_path", lambda path, cfg: "described-template")
    monkeypatch.setattr(pickers, "bundled_templates_dir", lambda: tmp_path / "bundled-templates")

    assert pickers.resolve_template_path("starter", cfg=cfg, candidates=[template_path]) == template_path
    assert pickers.resolve_template_path("described-template", cfg=cfg, candidates=[template_path]) == template_path


def test_select_include_candidate_handles_numeric_and_plain_paths(monkeypatch, tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    file_path = workspace / "doc.md"
    file_path.write_text("doc", encoding="utf-8")
    state = SimpleNamespace(last_candidates=[file_path])

    assert pickers.select_include_candidate("1", state) == file_path
    assert pickers.select_include_candidate("doc.md", state) == file_path
    assert pickers.select_include_candidate(str(tmp_path.parent / "outside.md"), state) is None
    assert "Path is outside the working directory" in capsys.readouterr().err


def test_has_glob_chars_detects_patterns():
    assert pickers.has_glob_chars("*.py") is True
    assert pickers.has_glob_chars("file?.py") is True
    assert pickers.has_glob_chars("[ab].py") is True
    assert pickers.has_glob_chars("plain.txt") is False


def test_select_include_candidates_supports_index_glob_limit_and_plain_path(monkeypatch, tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    alpha = workspace / "alpha.py"
    beta = workspace / "beta.py"
    alpha.write_text("a", encoding="utf-8")
    beta.write_text("b", encoding="utf-8")
    ignored = workspace / "__pycache__" / "ignored.py"
    ignored.parent.mkdir()
    ignored.write_text("ignored", encoding="utf-8")
    state = SimpleNamespace(last_candidates=[alpha, beta])

    monkeypatch.setattr(
        pickers.glob_module, "glob", lambda pattern, recursive=True: [str(beta), str(ignored), str(alpha)]
    )

    assert pickers.select_include_candidates("2", state) == [beta]
    assert pickers.select_include_candidates("*.py 1", state) == [alpha]
    assert pickers.select_include_candidates("alpha.py", state) == [alpha]

    monkeypatch.setattr(pickers.glob_module, "glob", lambda pattern, recursive=True: [])
    assert pickers.select_include_candidates("*.txt", state) is None
    assert "No files matched: *.txt" in capsys.readouterr().err
