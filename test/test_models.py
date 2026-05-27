"""Tests for domain models."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from tuochat.models import Conversation, Message, MessageStatus, Role, Usage

ROLE_VALUES = tuple(role.value for role in Role)
STATUS_VALUES = tuple(status.value for status in MessageStatus)
MESSAGE_FIELD_NAMES = frozenset(Message.__dataclass_fields__)
USAGE_FIELD_NAMES = frozenset(Usage.__dataclass_fields__)


def expected_auto_title(text: str | None) -> str:
    if text:
        stripped = text.strip()
        if stripped:
            return stripped[:57] + "..." if len(stripped) > 60 else stripped
    return "Untitled conversation"


def expected_auto_title_from_messages(messages: list[Message]) -> str:
    for message in messages:
        if message.role == Role.USER.value:
            text = (message.content or "").strip()
            if text:
                return text[:57] + "..." if len(text) > 60 else text
    return "Untitled conversation"


@st.composite
def message_dicts(draw):
    return {
        "id": draw(st.text(min_size=1, max_size=40)),
        "conversation_id": draw(st.text(max_size=40)),
        "role": draw(st.sampled_from(ROLE_VALUES)),
        "content": draw(st.text(max_size=200)),
        "request_id": draw(st.one_of(st.none(), st.text(max_size=40))),
        "status": draw(st.sampled_from(STATUS_VALUES)),
        "created_at": draw(st.text(min_size=1, max_size=60)),
        "extras_json": draw(st.one_of(st.none(), st.text(max_size=200))),
    }


@st.composite
def usage_dicts(draw):
    return {
        "id": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10_000))),
        "conversation_id": draw(st.one_of(st.none(), st.text(max_size=40))),
        "message_id": draw(st.one_of(st.none(), st.text(max_size=40))),
        "input_tokens": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000))),
        "output_tokens": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000))),
        "model": draw(st.one_of(st.none(), st.text(max_size=80))),
        "recorded_at": draw(st.text(min_size=1, max_size=60)),
    }


def unknown_field_dicts(field_names: frozenset[str]):
    return st.dictionaries(
        st.text(min_size=1, max_size=20).filter(lambda key: key not in field_names),
        st.integers(),
        max_size=4,
    )


@st.composite
def messages(draw):
    return Message.from_dict(draw(message_dicts()))


@st.composite
def non_user_messages(draw):
    data = draw(message_dicts())
    data["role"] = draw(st.sampled_from((Role.ASSISTANT.value, Role.SYSTEM.value)))
    return Message.from_dict(data)


def test_message_creation():
    """Test creating a message with defaults."""
    msg = Message(content="Hello")
    assert msg.content == "Hello"
    assert msg.role == Role.USER.value
    assert msg.status == MessageStatus.COMPLETE.value
    assert msg.id  # UUID generated


def test_message_roundtrip():
    """Test message serialization/deserialization."""
    msg = Message(content="test", role=Role.ASSISTANT.value)
    d = msg.to_dict()
    msg2 = Message.from_dict(d)
    assert msg2.content == msg.content
    assert msg2.role == msg.role
    assert msg2.id == msg.id


@given(message_dicts(), unknown_field_dicts(MESSAGE_FIELD_NAMES))
def test_message_from_dict_ignores_unknown_fields(data, extra_fields):
    """Message.from_dict should ignore unknown keys and preserve known data."""
    msg = Message.from_dict({**data, **extra_fields})
    assert msg.to_dict() == data


def test_conversation_creation():
    """Test creating a conversation."""
    conv = Conversation(title="Test Chat")
    assert conv.title == "Test Chat"
    assert conv.id  # UUID generated
    assert conv.messages == []


def test_conversation_add_message():
    """Test adding messages to a conversation."""
    conv = Conversation()
    msg = conv.add_message(Role.USER.value, "Hello")
    assert len(conv.messages) == 1
    assert msg.conversation_id == conv.id
    assert msg.content == "Hello"


def test_conversation_auto_title():
    """Test auto-generating a title from the first user message."""
    conv = Conversation()
    conv.add_message(Role.USER.value, "How do I create a merge request?")
    assert conv.auto_title() == "How do I create a merge request?"


def test_conversation_auto_title_long():
    """Test auto-title truncation for long messages."""
    conv = Conversation()
    conv.add_message(Role.USER.value, "x" * 100)
    title = conv.auto_title()
    assert len(title) <= 60
    assert title.endswith("...")


def test_conversation_auto_title_no_user_message():
    """Test auto-title with no user messages."""
    conv = Conversation()
    conv.add_message(Role.ASSISTANT.value, "Hello!")
    assert conv.auto_title() == "Untitled conversation"


def test_conversation_roundtrip():
    """Test conversation serialization excludes messages."""
    conv = Conversation(title="Test")
    conv.add_message(Role.USER.value, "Hello")
    d = conv.to_dict()
    assert "messages" not in d
    conv2 = Conversation.from_dict(d)
    assert conv2.title == conv.title
    assert conv2.id == conv.id


@given(
    st.text(max_size=80),
    st.text(max_size=200),
    st.one_of(st.none(), st.text(max_size=40)),
    st.sampled_from(STATUS_VALUES),
)
def test_conversation_add_message_preserves_inputs(role, content, request_id, status):
    """add_message should append one message and pass through explicit fields."""
    conv = Conversation()
    before_updated_at = conv.updated_at

    msg = conv.add_message(role, content, request_id=request_id, status=status)

    assert conv.messages[-1] == msg
    assert len(conv.messages) == 1
    assert msg.conversation_id == conv.id
    assert msg.role == role
    assert msg.content == content
    assert msg.request_id == request_id
    assert msg.status == status
    assert conv.updated_at >= before_updated_at


@given(
    st.one_of(st.none(), st.text(max_size=200)),
    st.lists(messages(), max_size=5),
)
def test_conversation_auto_title_prefers_explicit_first_user_text(first_user_text, seed_messages):
    """auto_title should prefer explicit first_user_text over stored messages."""
    conv = Conversation(messages=seed_messages)

    expected = expected_auto_title(first_user_text)
    if expected == "Untitled conversation":
        expected = expected_auto_title_from_messages(seed_messages)

    assert conv.auto_title(first_user_text) == expected


@given(st.lists(non_user_messages(), max_size=5), st.text(max_size=200))
def test_conversation_auto_title_uses_first_user_message(seed_messages, user_content):
    """auto_title should use the first stored user message when no explicit text is provided."""
    conv = Conversation(messages=[*seed_messages, Message(role=Role.USER.value, content=user_content)])

    assert conv.auto_title() == expected_auto_title(user_content)


@given(
    st.text(max_size=80),
    st.booleans(),
    st.one_of(st.none(), st.text(max_size=80)),
    st.one_of(st.none(), st.text(max_size=80)),
    st.lists(messages(), max_size=5),
)
def test_conversation_record_roundtrip(title, archived, resource_id, system_prompt, msgs):
    """Conversation records should round-trip nested messages."""
    conv = Conversation(
        title=title,
        archived=archived,
        resource_id=resource_id,
        system_prompt=system_prompt,
        messages=msgs,
    )

    restored = Conversation.from_record(conv.to_record())

    assert restored == conv


def test_usage_creation():
    """Test creating a usage record."""
    u = Usage(input_tokens=100, output_tokens=50, model="claude")
    assert u.input_tokens == 100
    assert u.output_tokens == 50
    d = u.to_dict()
    u2 = Usage.from_dict(d)
    assert u2.input_tokens == 100


@given(usage_dicts(), unknown_field_dicts(USAGE_FIELD_NAMES))
def test_usage_from_dict_ignores_unknown_fields(data, extra_fields):
    """Usage.from_dict should ignore unknown keys and preserve known data."""
    usage = Usage.from_dict({**data, **extra_fields})
    assert usage.to_dict() == data
