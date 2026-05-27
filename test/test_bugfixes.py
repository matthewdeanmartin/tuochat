"""Tests for context-management bug fixes and new features.

Covers:
- /context preview at 50 chars
- format_cost dollar formatting
- /include glob expansion (Windows-safe)
- /resume context replay
- /classify command
- /usage command
- Weekly usage store query
- Classification header in markdown output
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tuochat.cli.pickers import has_glob_chars, select_include_candidates
from tuochat.cli.rendering import context_preview
from tuochat.cli.repl import handle_slash_command, week_start_iso
from tuochat.cli.session import ReplState, build_outbound_input, build_resumed_context_block, switch_to_conversation
from tuochat.cli.setup import get_valid_classifications, prompt_classification
from tuochat.constants import CLASSIFICATION_UNCLASSIFIED, CLASSIFICATION_UNKNOWN
from tuochat.estimation import format_cost
from tuochat.models import Conversation, Message, Role, Usage
from tuochat.persistence.archive import render_conversation_markdown
from tuochat.persistence.store import ConversationStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """Create a temporary ConversationStore."""
    with ConversationStore(tmp_path / "test.db") as s:
        yield s


def make_state(tmp_path, store, *, cfg=None, conv=None):
    """Build a minimal ReplState for testing."""
    if conv is None:
        conv = Conversation(title="Test")
        if cfg is None:
            cfg = SimpleNamespace(
                data_dir=tmp_path,
                classification=SimpleNamespace(
                    enabled=False,
                    ask_per_conversation=True,
                    markings=[],
                    organizations=[],
                    max_markings=[],
                ),
            )
    return ReplState(
        conv=conv,
        store=store,
        provider=object(),
        cfg=cfg,
        streaming=True,
    )


# ---------------------------------------------------------------------------
# /context — 50-char preview
# ---------------------------------------------------------------------------


class TestContextPreview:
    def test_short_text_returned_verbatim(self):
        assert context_preview("hello", limit=50) == "hello"

    def test_text_exactly_50_chars_returned_verbatim(self):
        text = "x" * 50
        assert context_preview(text, limit=50) == text

    def test_text_over_50_truncated_with_ellipsis(self):
        text = "a" * 60
        result = context_preview(text, limit=50)
        assert result == "a" * 50 + "..."
        assert len(result) == 53

    def test_empty_text_returns_placeholder(self):
        assert context_preview("", limit=50) == "(empty)"

    def test_whitespace_normalized(self):
        result = context_preview("hello\n   world", limit=50)
        assert result == "hello world"

    def test_default_limit_is_25(self):
        """The plain context_preview default should still be 25."""
        text = "a" * 30
        result = context_preview(text)
        assert result == "a" * 25 + "..."


# ---------------------------------------------------------------------------
# format_cost
# ---------------------------------------------------------------------------


class TestFormatCost:
    def test_zero_is_zero_dollars(self):
        assert format_cost(0.0) == "$0.00"

    def test_one_cent_exact(self):
        assert format_cost(0.01) == "$0.01"

    def test_large_amount_two_decimal_places(self):
        assert format_cost(12.345) == "$12.35"

    def test_sub_cent_two_sig_figs(self):
        result = format_cost(0.0034)
        assert result == "$0.0034"

    def test_sub_cent_very_small(self):
        result = format_cost(0.00056)
        assert result == "$0.00056"

    def test_just_under_one_cent(self):
        result = format_cost(0.009)
        # 2 sig figs of 0.009 => 0.0090
        assert result.startswith("$0.00")
        assert "9" in result

    def test_typical_large_session(self):
        result = format_cost(1.5)
        assert result == "$1.50"

    def test_exactly_ten_cents(self):
        assert format_cost(0.10) == "$0.10"

    def test_sub_cent_1e_6(self):
        # 0.0000012 → 2 sig figs
        result = format_cost(0.0000012)
        assert result.startswith("$")
        assert float(result[1:]) > 0


# ---------------------------------------------------------------------------
# has_glob_chars / select_include_candidates
# ---------------------------------------------------------------------------


class TestGlobIncludes:
    def test_has_glob_star(self):
        assert has_glob_chars("*.py") is True

    def test_has_glob_question(self):
        assert has_glob_chars("file?.py") is True

    def test_has_glob_bracket(self):
        assert has_glob_chars("[abc].py") is True

    def test_no_glob_plain_path(self):
        assert has_glob_chars("README.md") is False

    def test_select_plain_file(self, tmp_path, store, monkeypatch):
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "hello.py"
        f.write_text("print('hi')")
        state = make_state(tmp_path, store)
        result = select_include_candidates("hello.py", state)
        assert result is not None
        assert len(result) == 1
        assert result[0] == tmp_path / "hello.py"

    def test_select_glob_matches_files(self, tmp_path, store, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "c.txt").write_text("c")
        state = make_state(tmp_path, store)
        result = select_include_candidates("*.py", state)
        assert result is not None
        names = {p.name for p in result}
        assert "a.py" in names
        assert "b.py" in names
        assert "c.txt" not in names

    def test_attach_alias_queues_file_for_next_request(self, tmp_path, store, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "notes.txt"
        target.write_text("hello", encoding="utf-8")
        state = make_state(tmp_path, store)

        message, should_exit = handle_slash_command("/attach notes.txt", state)

        assert message is None
        assert should_exit is False
        assert state.pending_attachment_names == [str(target)]

    def test_select_glob_with_limit(self, tmp_path, store, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for i in range(5):
            (tmp_path / f"file{i}.py").write_text(f"f{i}")
        state = make_state(tmp_path, store)
        result = select_include_candidates("*.py 3", state)
        assert result is not None
        assert len(result) == 3

    def test_select_glob_double_star(self, tmp_path, store, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "mod.py").write_text("x")
        (tmp_path / "top.py").write_text("y")
        state = make_state(tmp_path, store)
        result = select_include_candidates("**/*.py", state)
        assert result is not None
        names = {p.name for p in result}
        assert "mod.py" in names
        assert "top.py" in names

    def test_select_glob_no_matches_returns_none(self, tmp_path, store, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        state = make_state(tmp_path, store)
        result = select_include_candidates("*.nonexistent", state)
        assert result is None
        captured = capsys.readouterr()
        assert "No files matched" in captured.err

    def test_select_numeric_index(self, tmp_path, store, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "first.py").write_text("a")
        state = make_state(tmp_path, store)
        # Prime the candidate list
        state.last_candidates = [tmp_path / "first.py"]
        result = select_include_candidates("1", state)
        assert result is not None
        assert result[0].name == "first.py"

    def test_select_index_out_of_range(self, tmp_path, store, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        state = make_state(tmp_path, store)
        state.last_candidates = [tmp_path / "only.py"]
        result = select_include_candidates("99", state)
        assert result is None


# ---------------------------------------------------------------------------
# /resume — context replay
# ---------------------------------------------------------------------------


class TestResumeContextReplay:
    def test_resumed_context_block_includes_history(self):
        conv = Conversation(title="Old Chat")
        conv.add_message(Role.USER.value, "What is Python?")
        conv.add_message(Role.ASSISTANT.value, "Python is a language.")
        block = build_resumed_context_block(conv)
        assert "[USER]: What is Python?" in block
        assert "[ASSISTANT]: Python is a language." in block
        assert "End of prior context" in block

    def test_resumed_context_injected_on_first_message(self, tmp_path, store):
        conv = Conversation(title="Old Chat")
        conv.add_message(Role.USER.value, "Prior question")
        conv.add_message(Role.ASSISTANT.value, "Prior answer")
        state = make_state(tmp_path, store, conv=conv)
        state.resumed_context_pending = True

        outbound = build_outbound_input(state, "New question")

        assert "Prior question" in outbound
        assert "Prior answer" in outbound
        assert "New question" in outbound
        assert state.resumed_context_pending is False

    def test_resumed_context_not_injected_on_second_message(self, tmp_path, store):
        conv = Conversation(title="Old Chat")
        conv.add_message(Role.USER.value, "Prior question")
        state = make_state(tmp_path, store, conv=conv)
        state.resumed_context_pending = False

        outbound = build_outbound_input(state, "Follow-up")

        assert "Prior question" not in outbound
        assert "Follow-up" in outbound

    def test_switch_to_conversation_sets_flag(self, tmp_path):
        with ConversationStore(tmp_path / "test.db") as store:
            old_conv = Conversation(title="Old")
            store.save_conversation(old_conv)
            store.save_message(Message(conversation_id=old_conv.id, role=Role.USER.value, content="hello"))

            current_conv = Conversation(title="Current")
            cfg = SimpleNamespace(
                data_dir=tmp_path,
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, markings=[], organizations=[]
                ),
            )
            state = ReplState(conv=current_conv, store=store, provider=object(), cfg=cfg, streaming=True)
            state.resumed_context_pending = False

            with (
                patch("tuochat.cli.rendering.clear_screen"),
                patch("tuochat.cli.rendering.print_masked_conversation_transcript"),
                patch(
                    "tuochat.cli.session.sync_conversation_artifacts", return_value=(tmp_path, tmp_path / "conv.md", [])
                ),
            ):
                switch_to_conversation(state, old_conv)

            assert state.resumed_context_pending is True
            assert state.conv.id == old_conv.id

    def test_empty_conversation_does_not_set_flag(self, tmp_path):
        with ConversationStore(tmp_path / "test.db") as store:
            empty_conv = Conversation(title="Empty")
            store.save_conversation(empty_conv)

            current_conv = Conversation(title="Current")
            cfg = SimpleNamespace(
                data_dir=tmp_path,
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, markings=[], organizations=[]
                ),
            )
            state = ReplState(conv=current_conv, store=store, provider=object(), cfg=cfg, streaming=True)

            with (
                patch("tuochat.cli.rendering.clear_screen"),
                patch("tuochat.cli.rendering.print_masked_conversation_transcript"),
                patch(
                    "tuochat.cli.session.sync_conversation_artifacts", return_value=(tmp_path, tmp_path / "conv.md", [])
                ),
            ):
                switch_to_conversation(state, empty_conv)

            assert state.resumed_context_pending is False


# ---------------------------------------------------------------------------
# /classify command
# ---------------------------------------------------------------------------


class TestClassifyCommand:
    def cfg(self, markings=None):
        return SimpleNamespace(
            data_dir=Path("/tmp"),
            classification=SimpleNamespace(
                enabled=True,
                ask_per_conversation=True,
                markings=markings or ["FOUO", "SECRET", "TOP SECRET"],
                organizations=[],
                max_markings=[],
            ),
        )

    def test_classify_with_argument_sets_classification(self, tmp_path, capsys):
        cfg = self.cfg()
        with ConversationStore(tmp_path / "test.db") as store:
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            msg, exit_ = handle_slash_command("/classify FOUO", state)
            assert msg is None
            assert exit_ is False
            assert state.active_classification == "FOUO"

    def test_classify_case_insensitive_match(self, tmp_path):
        cfg = self.cfg()
        with ConversationStore(tmp_path / "test.db") as store:
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            handle_slash_command("/classify secret", state)
            assert state.active_classification == "SECRET"

    def test_classify_interactive_pick_by_number(self, tmp_path, capsys):
        cfg = self.cfg()
        with ConversationStore(tmp_path / "test.db") as store:
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            # Options are: [1] Classification pending review [2] Unclassified [3] FOUO [4] SECRET [5] TOP SECRET
            with patch("builtins.input", return_value="3"):
                handle_slash_command("/classify", state)
            assert state.active_classification == "FOUO"

    def test_classify_pending_review_is_valid(self, tmp_path):
        cfg = self.cfg()
        with ConversationStore(tmp_path / "test.db") as store:
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            with patch("builtins.input", return_value="1"):
                handle_slash_command("/classify", state)
            assert state.active_classification == CLASSIFICATION_UNKNOWN

    def test_classify_unclassified_is_valid(self, tmp_path):
        cfg = self.cfg()
        with ConversationStore(tmp_path / "test.db") as store:
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            with patch("builtins.input", return_value="2"):
                handle_slash_command("/classify", state)
            assert state.active_classification == CLASSIFICATION_UNCLASSIFIED

    def test_get_valid_classifications_always_includes_unknown(self):
        cfg = SimpleNamespace(
            classification=SimpleNamespace(markings=["FOUO", "SECRET"], organizations=[], max_markings=[])
        )
        options = get_valid_classifications(cfg)
        assert options[:2] == [CLASSIFICATION_UNKNOWN, CLASSIFICATION_UNCLASSIFIED]
        assert "FOUO" in options
        assert "SECRET" in options

    def test_get_valid_classifications_no_markings(self):
        cfg = SimpleNamespace(classification=SimpleNamespace(markings=[], organizations=[], max_markings=[]))
        options = get_valid_classifications(cfg)
        assert options == [CLASSIFICATION_UNKNOWN, CLASSIFICATION_UNCLASSIFIED]

    def test_classify_rejects_above_maximum(self, tmp_path, capsys):
        cfg = self.cfg()
        cfg.classification.max_markings = ["SECRET"]
        with ConversationStore(tmp_path / "test.db") as store:
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            msg, exit_ = handle_slash_command("/classify TOP SECRET", state)
            assert msg is None
            assert exit_ is False
            assert state.active_classification is None
            assert "No classifications higher than SECRET (Secret)." in capsys.readouterr().err

    def test_prompt_classification_reasks_when_above_maximum(self, tmp_path):
        cfg = self.cfg()
        cfg.classification.max_markings = ["SECRET"]
        with patch("builtins.input", side_effect=["5", "4"]):
            chosen = prompt_classification(cfg)
        assert chosen == "SECRET"


# ---------------------------------------------------------------------------
# /usage command
# ---------------------------------------------------------------------------


class TestUsageCommand:
    def test_usage_shows_weekly_totals(self, tmp_path, capsys):
        with ConversationStore(tmp_path / "test.db") as store:
            conv = Conversation()
            store.save_conversation(conv)
            msg = Message(conversation_id=conv.id, role=Role.ASSISTANT.value, content="hi")
            store.save_message(msg)
            store.save_usage(
                Usage(
                    conversation_id=conv.id,
                    message_id=msg.id,
                    input_tokens=1000,
                    output_tokens=500,
                )
            )
            cfg = SimpleNamespace(
                data_dir=tmp_path,
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, markings=[], organizations=[]
                ),
            )
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            result, exit_ = handle_slash_command("/usage", state)
            assert result is None
            assert exit_ is False
            captured = capsys.readouterr()
            assert "Weekly usage" in captured.out
            assert "Input Tokens: 1,000" in captured.out
            assert "Output Tokens: 500" in captured.out
            assert "Total Tokens: 1,500" in captured.out

    def test_usage_shows_zero_when_no_data(self, tmp_path, capsys):
        with ConversationStore(tmp_path / "test.db") as store:
            cfg = SimpleNamespace(
                data_dir=tmp_path,
                classification=SimpleNamespace(
                    enabled=False, ask_per_conversation=False, markings=[], organizations=[]
                ),
            )
            state = ReplState(conv=Conversation(), store=store, provider=object(), cfg=cfg, streaming=True)
            handle_slash_command("/usage", state)
            captured = capsys.readouterr()
            assert "Turns: 0" in captured.out
            assert "Approximate Kilobytes: 0.0" in captured.out


# ---------------------------------------------------------------------------
# Weekly usage store query
# ---------------------------------------------------------------------------


class TestWeeklyUsageStore:
    @pytest.fixture()
    def store(self, tmp_path):
        with ConversationStore(tmp_path / "test.db") as s:
            yield s

    def save_usage(self, store, input_tok, output_tok, *, recorded_at=None):
        conv = Conversation()
        store.save_conversation(conv)
        msg = Message(conversation_id=conv.id, role=Role.ASSISTANT.value, content="x")
        store.save_message(msg)
        u = Usage(
            conversation_id=conv.id,
            message_id=msg.id,
            input_tokens=input_tok,
            output_tokens=output_tok,
        )
        if recorded_at:
            u.recorded_at = recorded_at
        store.save_usage(u)

    def test_sums_within_week(self, store):
        week_start = week_start_iso()
        self.save_usage(store, 100, 50)
        self.save_usage(store, 200, 100)
        result = store.get_weekly_usage(week_start)
        assert result["input_tokens"] == 300
        assert result["output_tokens"] == 150
        assert result["total_tokens"] == 450
        assert result["turns"] == 2

    def test_excludes_data_before_week_start(self, store):
        old_ts = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        self.save_usage(store, 9999, 9999, recorded_at=old_ts)
        self.save_usage(store, 100, 50)
        week_start = week_start_iso()
        result = store.get_weekly_usage(week_start)
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["turns"] == 1

    def test_empty_returns_zeros(self, store):
        result = store.get_weekly_usage(week_start_iso())
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "turns": 0}

    def test_week_start_is_sunday(self):
        start = week_start_iso()
        dt = datetime.fromisoformat(start)
        # Python weekday: Mon=0 … Sun=6
        assert dt.weekday() == 6 or dt.weekday() == 0  # Sunday (6) or Monday (0 when today IS Sunday)
        # More precisely: the result should be the most recent Sunday
        now = datetime.now(timezone.utc)
        days_since_sunday = (now.weekday() + 1) % 7
        expected_sunday = (now - timedelta(days=days_since_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)
        assert dt.date() == expected_sunday.date()


# ---------------------------------------------------------------------------
# Classification header in markdown output
# ---------------------------------------------------------------------------


class TestClassificationMarkdown:
    def test_classification_header_in_output(self):
        conv = Conversation(title="Test Conv")
        conv.add_message(Role.USER.value, "hello")
        conv.add_message(Role.ASSISTANT.value, "hi")
        md = render_conversation_markdown(conv, classification="SECRET")
        assert "**CLASSIFICATION: SECRET**" in md
        assert "<!-- Classification: SECRET -->" in md
        assert "Classification: SECRET (Secret)" in md

    def test_no_header_when_classification_none(self):
        conv = Conversation(title="Test")
        md = render_conversation_markdown(conv)
        assert "CLASSIFICATION" not in md
        assert "<!-- Classification" not in md

    def test_no_header_for_pending_review(self):
        conv = Conversation(title="Test")
        md = render_conversation_markdown(conv, classification=CLASSIFICATION_UNKNOWN)
        assert "CLASSIFICATION" not in md

    def test_classification_appears_before_title(self):
        conv = Conversation(title="My Chat")
        md = render_conversation_markdown(conv, classification="FOUO")
        fouo_pos = md.find("CLASSIFICATION: FOUO")
        title_pos = md.find("# My Chat")
        assert fouo_pos < title_pos

    def test_messages_still_present(self):
        conv = Conversation(title="Test")
        conv.add_message(Role.USER.value, "question")
        conv.add_message(Role.ASSISTANT.value, "answer")
        md = render_conversation_markdown(conv, classification="CUI")
        assert "question" in md
        assert "answer" in md
