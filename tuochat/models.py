"""Domain models for tuochat.

Plain dataclasses representing conversations, messages, and usage.
Serializable to/from dicts for JSON and sqlite storage.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Message role."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """Message completion status."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


def dataclass_field_names(model_type: type[Any]) -> set[str]:
    """Return the declared field names for a dataclass type."""
    return {item.name for item in fields(model_type)}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Message:
    """A single message in a conversation."""

    id: str = field(default_factory=new_id)
    conversation_id: str = ""
    role: str = Role.USER.value
    content: str = ""
    request_id: str | None = None
    status: str = MessageStatus.COMPLETE.value
    created_at: str = field(default_factory=utcnow)
    extras_json: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Deserialize from a dict."""
        allowed_fields = dataclass_field_names(cls)
        return cls(**{key: value for key, value in data.items() if key in allowed_fields})


@dataclass
class Conversation:
    """A chat conversation (collection of messages)."""

    id: str = field(default_factory=new_id)
    title: str | None = None
    archived: bool = False
    resource_id: str | None = None
    system_prompt: str | None = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    cwd: str | None = None
    messages: list[Message] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict (without messages)."""
        d = asdict(self)
        d.pop("messages", None)
        return d

    def to_record(self) -> dict[str, Any]:
        """Serialize a conversation including messages for JSON round-tripping."""
        data = self.to_dict()
        data["messages"] = [message.to_dict() for message in self.messages]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Conversation:
        """Deserialize from a dict (without messages)."""
        allowed_fields = dataclass_field_names(cls)
        filtered = {key: value for key, value in data.items() if key in allowed_fields and key != "messages"}
        return cls(**filtered)

    @classmethod
    def from_record(cls, data: dict[str, Any]) -> Conversation:
        """Deserialize a conversation including messages from JSON-friendly data."""
        conv = cls.from_dict(data)
        conv.messages = [Message.from_dict(item) for item in data.get("messages", [])]
        return conv

    def add_message(self, role: str, content: str, **kwargs: Any) -> Message:
        """Create and append a message to this conversation."""
        msg = Message(
            conversation_id=self.id,
            role=role,
            content=content,
            **kwargs,
        )
        self.messages.append(msg)
        self.updated_at = utcnow()
        return msg

    def auto_title(self, first_user_text: str | None = None) -> str:
        """Generate a title from the first user message.

        Pass first_user_text to use the raw user input rather than the stored
        message content (which may include attachment payloads).
        """
        if first_user_text:
            text = first_user_text.strip()
            if text:
                return text[:57] + "..." if len(text) > 60 else text
        for msg in self.messages:
            if msg.role == Role.USER.value and msg.content:
                text = msg.content.strip()
                if not text:
                    continue
                if len(text) > 60:
                    return text[:57] + "..."
                return text
        return "Untitled conversation"


@dataclass
class Usage:
    """Token usage record for a single message exchange."""

    id: int | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    recorded_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Usage:
        """Deserialize from a dict."""
        allowed_fields = dataclass_field_names(cls)
        return cls(**{key: value for key, value in data.items() if key in allowed_fields})


@dataclass
class ConversationSearchResult:
    """A full-text search match for a conversation."""

    conversation_id: str
    message_id: str
    role: str
    archived: bool = False
    title: str | None = None
    updated_at: str | None = None
    created_at: str | None = None
    snippet: str = ""
