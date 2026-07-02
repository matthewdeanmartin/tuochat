"""Tests for the OpenRouter wiring in tuochat.cli.session."""

from __future__ import annotations

from pathlib import Path

import pytest

from tuochat.cli.models import ReplState
from tuochat.cli.session import build_openrouter_provider, conversation_history_for_openrouter
from tuochat.config import TuochatConfig
from tuochat.models import Conversation
from tuochat.persistence.store import NullConversationStore
from tuochat.provider.eliza import ElizaProvider
from tuochat.provider.openrouter import OpenRouterAPIError


def make_state_stub(conversation: Conversation) -> ReplState:
    """Build a typed state object exposing the conversation history."""
    cfg = TuochatConfig()
    return ReplState(
        conv=conversation,
        store=NullConversationStore(Path("unused.db")),
        provider=ElizaProvider(),
        cfg=cfg,
        streaming=True,
    )


def test_build_openrouter_provider_requires_api_key():
    cfg = TuochatConfig()
    cfg.openrouter.api_key = ""
    cfg.openrouter.models = ["openai/gpt-4.1-mini"]
    with pytest.raises(OpenRouterAPIError, match="API key"):
        build_openrouter_provider(cfg)


def test_build_openrouter_provider_requires_models():
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-test"
    cfg.openrouter.model = ""
    cfg.openrouter.models = []
    with pytest.raises(OpenRouterAPIError, match="model"):
        build_openrouter_provider(cfg)


def test_build_openrouter_provider_uses_effective_models_and_rotation():
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-test"
    cfg.openrouter.models = ["openai/gpt-4.1-mini", "openrouter/free"]
    cfg.openrouter.rotate_models = True
    cfg.openrouter.base_url = "https://router.example.test/v1"
    provider = build_openrouter_provider(cfg)
    assert provider.models == ["openai/gpt-4.1-mini", "openrouter/free"]
    assert provider.rotate_models is True
    assert provider.base_url == "https://router.example.test/v1"


def test_build_openrouter_provider_override_pins_single_model_and_disables_rotation():
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-test"
    cfg.openrouter.models = ["a", "b", "c"]
    cfg.openrouter.rotate_models = True
    provider = build_openrouter_provider(cfg, model_override="explicit")
    assert provider.models == ["explicit"]
    assert provider.rotate_models is False


def test_conversation_history_for_openrouter_filters_and_orders_messages():
    conv = Conversation()
    conv.add_message("user", "hello")
    conv.add_message("assistant", "hi there")
    conv.add_message("system", "background")
    conv.add_message("tool", "ignored")
    conv.add_message("user", "")  # empty content stripped
    state = make_state_stub(conv)
    history = conversation_history_for_openrouter(state)
    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "system", "content": "background"},
    ]


def test_conversation_history_empty_for_new_conversation():
    state = make_state_stub(Conversation())
    assert conversation_history_for_openrouter(state) == []
