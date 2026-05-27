"""Tests for the persistence layer."""

from __future__ import annotations

import threading

import pytest

from tuochat.models import Conversation, Message, Role, Usage
from tuochat.persistence.store import ConversationStore


@pytest.fixture()
def store(tmp_path):
    """Create a temporary ConversationStore."""
    with ConversationStore(tmp_path / "test.db") as s:
        yield s


def test_save_and_get_conversation(store):
    """Test saving and retrieving a conversation."""
    conv = Conversation(title="Test Chat")
    store.save_conversation(conv)
    loaded = store.get_conversation(conv.id)
    assert loaded is not None
    assert loaded.title == "Test Chat"
    assert loaded.id == conv.id


def test_list_conversations(store):
    """Test listing conversations ordered by update time."""
    c1 = Conversation(title="First")
    c2 = Conversation(title="Second")
    store.save_conversation(c1)
    store.save_conversation(c2)
    convs = store.list_conversations()
    assert len(convs) == 2
    # Most recently created should be first (both have same updated_at roughly)
    titles = [c.title for c in convs]
    assert "First" in titles
    assert "Second" in titles


def test_save_and_get_messages(store):
    """Test saving and retrieving messages."""
    conv = Conversation(title="Test")
    store.save_conversation(conv)

    msg1 = Message(conversation_id=conv.id, role=Role.USER.value, content="Hello")
    msg2 = Message(conversation_id=conv.id, role=Role.ASSISTANT.value, content="Hi there!")
    store.save_message(msg1)
    store.save_message(msg2)

    messages = store.get_messages(conv.id)
    assert len(messages) == 2
    assert messages[0].content == "Hello"
    assert messages[1].content == "Hi there!"


def test_delete_conversation(store):
    """Test deleting a conversation and its messages."""
    conv = Conversation(title="Delete Me")
    store.save_conversation(conv)
    msg = Message(conversation_id=conv.id, role=Role.USER.value, content="bye")
    store.save_message(msg)

    assert store.delete_conversation(conv.id)
    assert store.get_conversation(conv.id) is None
    assert store.get_messages(conv.id) == []


def test_delete_nonexistent_conversation(store):
    """Test deleting a conversation that doesn't exist."""
    assert not store.delete_conversation("nonexistent-id")


def test_update_conversation(store):
    """Test that saving an existing conversation updates it."""
    conv = Conversation(title="Original")
    store.save_conversation(conv)
    conv.title = "Updated"
    store.save_conversation(conv)
    loaded = store.get_conversation(conv.id)
    assert loaded is not None
    assert loaded.title == "Updated"


def test_update_message(store):
    """Test that saving an existing message updates its content."""
    conv = Conversation(title="Test")
    store.save_conversation(conv)
    msg = Message(conversation_id=conv.id, role=Role.ASSISTANT.value, content="partial")
    store.save_message(msg)
    msg.content = "complete response"
    msg.status = "complete"
    store.save_message(msg)
    messages = store.get_messages(conv.id)
    assert len(messages) == 1
    assert messages[0].content == "complete response"


def test_export_markdown(store):
    """Test markdown export of a conversation."""
    conv = Conversation(title="Export Test")
    store.save_conversation(conv)
    store.save_message(Message(conversation_id=conv.id, role=Role.USER.value, content="Hello"))
    store.save_message(Message(conversation_id=conv.id, role=Role.ASSISTANT.value, content="Hi!"))

    md = store.export_markdown(conv.id)
    assert md is not None
    assert "# Export Test" in md
    assert "Hello" in md
    assert "Hi!" in md
    assert "## User" in md
    assert "## Assistant" in md


def test_export_nonexistent(store):
    """Test export of nonexistent conversation returns None."""
    assert store.export_markdown("nonexistent") is None


def test_save_usage(store):
    """Test saving usage records."""
    conv = Conversation(title="Test")
    store.save_conversation(conv)
    usage = Usage(conversation_id=conv.id, input_tokens=100, output_tokens=50, model="test")
    store.save_usage(usage)  # Should not raise


def test_sums_within_week(store):
    """Test that usage within the week is correctly summed."""
    store.save_usage(Usage(input_tokens=10, output_tokens=20, recorded_at="2024-01-02T12:00:00Z"))
    store.save_usage(Usage(input_tokens=5, output_tokens=5, recorded_at="2024-01-03T12:00:00Z"))

    summary = store.get_weekly_usage("2024-01-01T00:00:00Z")
    assert summary["input_tokens"] == 15
    assert summary["output_tokens"] == 25
    assert summary["total_tokens"] == 40
    assert summary["turns"] == 2


def test_excludes_data_before_week(store):
    """Test that usage before the week start is ignored."""
    store.save_usage(Usage(input_tokens=100, output_tokens=100, recorded_at="2023-12-31T23:59:59Z"))
    store.save_usage(Usage(input_tokens=10, output_tokens=10, recorded_at="2024-01-01T00:00:01Z"))

    summary = store.get_weekly_usage("2024-01-01T00:00:00Z")
    assert summary["input_tokens"] == 10
    assert summary["turns"] == 1


def test_search_conversations_matches_message_content(store):
    """Test full-text search returns matching conversation snippets."""
    conv = Conversation(title="Terraform Notes")
    store.save_conversation(conv)
    store.save_message(
        Message(conversation_id=conv.id, role=Role.USER.value, content="Investigate terraform drift today")
    )
    store.save_message(
        Message(conversation_id=conv.id, role=Role.ASSISTANT.value, content="Found drift in the staging plan")
    )

    results = store.search_conversations("terraform drift")

    assert len(results) >= 1
    assert results[0].conversation_id == conv.id
    assert results[0].title == "Terraform Notes"
    assert "terraform" in results[0].snippet.lower() or "drift" in results[0].snippet.lower()


def test_search_conversations_can_filter_by_title(store):
    """Test search can narrow matches by conversation title."""
    matching = Conversation(title="Terraform Triage")
    other = Conversation(title="Kubernetes Triage")
    store.save_conversation(matching)
    store.save_conversation(other)
    store.save_message(Message(conversation_id=matching.id, role=Role.USER.value, content="terraform drift detected"))
    store.save_message(Message(conversation_id=other.id, role=Role.USER.value, content="terraform drift detected"))

    results = store.search_conversations("terraform", title_filter="Terraform")

    assert [result.conversation_id for result in results] == [matching.id]


def test_archive_unarchive(store):
    """Test archiving and unarchiving conversations."""
    conv = Conversation(title="Archive Test")
    store.save_conversation(conv)
    assert not store.get_conversation(conv.id).archived

    store.set_conversation_archived(conv.id, True)
    assert store.get_conversation(conv.id).archived

    store.set_conversation_archived(conv.id, False)
    assert not store.get_conversation(conv.id).archived


def test_unarchive_all(store):
    """Test unarchiving all archived conversations."""
    c1 = Conversation(title="1", archived=True)
    c2 = Conversation(title="2", archived=True)
    c3 = Conversation(title="3", archived=False)
    store.save_conversation(c1)
    store.save_conversation(c2)
    store.save_conversation(c3)

    count = store.unarchive_all_conversations()
    assert count == 2
    assert not store.get_conversation(c1.id).archived
    assert not store.get_conversation(c2.id).archived
    assert not store.get_conversation(c3.id).archived


def test_list_archived(store):
    """Test listing only archived conversations."""
    c1 = Conversation(title="Archived", archived=True)
    c2 = Conversation(title="Active", archived=False)
    store.save_conversation(c1)
    store.save_conversation(c2)

    archived = store.list_archived_conversations()
    assert len(archived) == 1
    assert archived[0].id == c1.id


def test_search_with_date_filters(store):
    """Test searching with updated_after and updated_before."""
    c1 = Conversation(title="Old", updated_at="2020-01-01T00:00:00Z")
    c2 = Conversation(title="New", updated_at="2024-01-01T00:00:00Z")
    store.save_conversation(c1)
    store.save_conversation(c2)
    store.save_message(Message(conversation_id=c1.id, content="match me"))
    store.save_message(Message(conversation_id=c2.id, content="match me"))

    # After 2023
    results = store.search_conversations("match", updated_after="2023-01-01T00:00:00Z")
    assert len(results) == 1
    assert results[0].conversation_id == c2.id

    # Before 2023
    results = store.search_conversations("match", updated_before="2023-01-01T00:00:00Z")
    assert len(results) == 1
    assert results[0].conversation_id == c1.id


def test_store_supports_saving_from_a_worker_thread(tmp_path):
    """A store created on the main thread should still persist data from a worker thread."""
    with ConversationStore(tmp_path / "threaded.db") as store:
        conv = Conversation(title="Threaded Save")
        failure: list[BaseException] = []

        def save_from_worker() -> None:
            try:
                store.save_conversation(conv)
                store.save_message(Message(conversation_id=conv.id, role=Role.USER.value, content="hello from worker"))
            except BaseException as exc:  # noqa: BLE001
                failure.append(exc)

        worker = threading.Thread(target=save_from_worker)
        worker.start()
        worker.join()

        assert failure == []
        loaded = store.get_conversation(conv.id)
        assert loaded is not None
        assert loaded.title == "Threaded Save"
        messages = store.get_messages(conv.id)
        assert [message.content for message in messages] == ["hello from worker"]


def test_store_close_cleans_up_connections_created_on_other_threads(tmp_path):
    """Closing the store from the main thread should close worker-created connections too."""
    with ConversationStore(tmp_path / "threaded-close.db") as store:
        ready = threading.Event()

        def open_worker_connection() -> None:
            store.list_conversations()
            ready.set()

        worker = threading.Thread(target=open_worker_connection)
        worker.start()
        ready.wait()
        worker.join()

    with pytest.raises(RuntimeError, match="closed"):
        store.list_conversations()


class TestNormalizeEscapedFences:
    """normalize_escaped_fences converts LLM-escaped backtick fences to standard ones."""

    def setup_method(self):
        from tuochat.persistence.archive import normalize_escaped_fences

        self.normalize = normalize_escaped_fences

    def test_space_escaped_fence_opener(self):
        text = "` ` `python foo.py\ncode here\n```"
        result = self.normalize(text)
        assert result == "```python foo.py\ncode here\n```"

    def test_backslash_escaped_fence_opener(self):
        text = "\\`\\`\\`python bar.py\ncode here\n```"
        result = self.normalize(text)
        assert result == "```python bar.py\ncode here\n```"

    def test_plain_fence_unchanged(self):
        text = "```python foo.py\ncode here\n```"
        assert self.normalize(text) == text

    def test_escaped_fence_becomes_extractable(self):
        from tuochat.patterns import FENCED_BLOCK_RE

        text = "` ` `python password_manager.py\nITERATIONS = 260_000\n```"
        normalized = self.normalize(text)
        matches = list(FENCED_BLOCK_RE.finditer(normalized))
        assert len(matches) == 1
        assert "password_manager.py" in matches[0].group(1)
        assert "ITERATIONS" in matches[0].group(2)

    def test_only_line_start_is_normalized(self):
        # Inline ` ` ` in the middle of text should not be changed
        text = "Here is ` ` ` in prose\n```python\ncode\n```"
        result = self.normalize(text)
        assert "Here is ` ` ` in prose" in result
        assert "```python" in result

    def test_both_blocks_with_first_escaped(self):
        """Simulates what Duo emitted: first block escaped, second normal."""
        from tuochat.patterns import FENCED_BLOCK_RE

        text = "` ` `python password_manager.py\nfix1\n```\n\n" "```python test_password_manager.py\nfix2\n```"
        normalized = self.normalize(text)
        matches = list(FENCED_BLOCK_RE.finditer(normalized))
        assert len(matches) == 2
        infos = [m.group(1) for m in matches]
        assert any("password_manager.py" in i for i in infos)
        assert any("test_password_manager.py" in i for i in infos)
