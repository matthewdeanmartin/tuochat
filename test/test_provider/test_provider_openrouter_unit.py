"""Unit tests for the OpenRouter provider and its supporting helpers."""

from __future__ import annotations

from typing import Any

import pytest

from tuochat.provider import openrouter as openrouter_module
from tuochat.provider.openrouter import (
    OpenRouterAPIError,
    OpenRouterProvider,
    OpenRouterUnavailableError,
    extract_delta_text,
    extract_full_text,
)


class FakeChat:
    def __init__(self, events_or_response: Any, *, raise_on_send: Exception | None = None) -> None:
        self.events_or_response = events_or_response
        self.raise_on_send = raise_on_send
        self.last_kwargs: dict[str, Any] | None = None

    def send(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        if self.raise_on_send is not None:
            raise self.raise_on_send
        return self.events_or_response


class FakeClient:
    def __init__(self, chat: FakeChat) -> None:
        self.chat = chat


class FakeSDK:
    def __init__(self, chat: FakeChat) -> None:
        self.chat = chat
        self.constructor_kwargs: dict[str, Any] | None = None

    def OpenRouter(self, **kwargs: Any) -> FakeClient:  # noqa: N802 — match SDK class name
        self.constructor_kwargs = kwargs
        return FakeClient(self.chat)


def install_fake_sdk(monkeypatch: pytest.MonkeyPatch, chat: FakeChat) -> FakeSDK:
    sdk = FakeSDK(chat)
    monkeypatch.setattr(openrouter_module, "import_openrouter_sdk", lambda: sdk)
    return sdk


# ---------------------------------------------------------------------------
# Helper extraction
# ---------------------------------------------------------------------------


def test_extract_delta_text_handles_dict_event():
    event = {"choices": [{"delta": {"content": "hello"}}]}
    assert extract_delta_text(event) == "hello"


def test_extract_delta_text_handles_object_event():
    class Delta:
        content = " world"

    class Choice:
        delta = Delta()

    class Event:
        choices = [Choice()]

    assert extract_delta_text(Event()) == " world"


def test_extract_delta_text_returns_empty_for_missing_fields():
    assert extract_delta_text(None) == ""
    assert extract_delta_text({}) == ""
    assert extract_delta_text({"choices": []}) == ""
    assert extract_delta_text({"choices": [{"delta": {}}]}) == ""


def test_extract_full_text_dict_response():
    response = {"choices": [{"message": {"content": "complete"}}]}
    assert extract_full_text(response) == "complete"


def test_extract_full_text_object_response():
    class Message:
        content = "complete"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    assert extract_full_text(Response()) == "complete"


def test_extract_full_text_returns_empty_for_missing_fields():
    assert extract_full_text(None) == ""
    assert extract_full_text({"choices": []}) == ""
    assert extract_full_text({"choices": [{}]}) == ""


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_provider_requires_api_key():
    with pytest.raises(ValueError, match="API key"):
        OpenRouterProvider(api_key="", models=["openai/gpt-4.1-mini"])


def test_provider_requires_at_least_one_model():
    with pytest.raises(ValueError, match="model"):
        OpenRouterProvider(api_key="sk-test", models=[])


def test_provider_strips_blank_models():
    provider = OpenRouterProvider(api_key="sk-test", models=["", "  ", "openai/gpt-4.1-mini"])
    assert provider.models == ["openai/gpt-4.1-mini"]


# ---------------------------------------------------------------------------
# Model rotation
# ---------------------------------------------------------------------------


def test_select_model_no_rotation_returns_first():
    provider = OpenRouterProvider(
        api_key="sk-test",
        models=["a", "b", "c"],
        rotate_models=False,
    )
    assert provider.select_model() == "a"
    assert provider.select_model() == "a"


def test_select_model_rotates_through_list():
    provider = OpenRouterProvider(
        api_key="sk-test",
        models=["a", "b", "c"],
        rotate_models=True,
    )
    assert [provider.select_model() for _ in range(7)] == ["a", "b", "c", "a", "b", "c", "a"]


def test_select_model_single_entry_does_not_rotate():
    provider = OpenRouterProvider(api_key="sk-test", models=["only"], rotate_models=True)
    assert provider.select_model() == "only"
    assert provider.select_model() == "only"


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


def test_build_messages_includes_system_history_and_user():
    provider = OpenRouterProvider(api_key="sk-test", models=["x"])
    messages = provider.build_messages(
        "what time is it?",
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        system_prompt="be terse",
        additional_context=None,
    )
    assert messages[0] == {"role": "system", "content": "be terse"}
    assert messages[1] == {"role": "user", "content": "hi"}
    assert messages[2] == {"role": "assistant", "content": "hello"}
    assert messages[-1] == {"role": "user", "content": "what time is it?"}


def test_build_messages_folds_additional_context_into_system_message():
    provider = OpenRouterProvider(api_key="sk-test", models=["x"])
    messages = provider.build_messages(
        "go",
        history=None,
        system_prompt=None,
        additional_context=[
            {"category": "FILE", "name": "main.py", "content": "print('hi')"},
        ],
    )
    assert messages[0]["role"] == "system"
    assert "FILE" in messages[0]["content"]
    assert "main.py" in messages[0]["content"]
    assert "print('hi')" in messages[0]["content"]


def test_build_messages_skips_invalid_history_entries():
    provider = OpenRouterProvider(api_key="sk-test", models=["x"])
    messages = provider.build_messages(
        "next",
        history=[
            {"role": "tool", "content": "ignored"},
            {"role": "user", "content": "kept"},
            {"role": "user", "content": None},
        ],
        system_prompt=None,
        additional_context=None,
    )
    contents = [m["content"] for m in messages]
    assert "ignored" not in contents
    assert "kept" in contents


# ---------------------------------------------------------------------------
# chat() — streaming
# ---------------------------------------------------------------------------


def test_chat_streaming_yields_deltas(monkeypatch: pytest.MonkeyPatch):
    events = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {"content": " world"}}]},
        {"choices": [{"delta": {}}]},  # empty terminator
    ]
    chat = FakeChat(events_or_response=iter(events))
    install_fake_sdk(monkeypatch, chat)

    provider = OpenRouterProvider(api_key="sk-test", models=["openai/gpt-4.1-mini"])
    deltas = list(provider.chat("hi", streaming=True))
    assert "".join(deltas) == "Hello world"
    assert chat.last_kwargs is not None
    assert chat.last_kwargs["stream"] is True
    assert chat.last_kwargs["model"] == "openai/gpt-4.1-mini"
    assert chat.last_kwargs["messages"][-1] == {"role": "user", "content": "hi"}


def test_chat_streaming_stops_on_cancel(monkeypatch: pytest.MonkeyPatch):
    events = [
        {"choices": [{"delta": {"content": "first"}}]},
        {"choices": [{"delta": {"content": "second"}}]},
        {"choices": [{"delta": {"content": "third"}}]},
    ]
    chat = FakeChat(events_or_response=iter(events))
    install_fake_sdk(monkeypatch, chat)

    cancelled_after = {"count": 0}

    def cancel() -> bool:
        cancelled_after["count"] += 1
        return cancelled_after["count"] > 1

    provider = OpenRouterProvider(api_key="sk-test", models=["x"])
    deltas = list(provider.chat("go", streaming=True, cancel=cancel))
    assert deltas == ["first"]


def test_chat_non_streaming_returns_full_text(monkeypatch: pytest.MonkeyPatch):
    response = {"choices": [{"message": {"content": "complete answer"}}]}
    chat = FakeChat(events_or_response=response)
    install_fake_sdk(monkeypatch, chat)

    provider = OpenRouterProvider(api_key="sk-test", models=["x"])
    result = list(provider.chat("hi", streaming=False))
    assert result == ["complete answer"]
    assert chat.last_kwargs["stream"] is False


def test_chat_send_failure_wraps_in_openrouter_api_error(monkeypatch: pytest.MonkeyPatch):
    chat = FakeChat(events_or_response=None, raise_on_send=RuntimeError("boom"))
    install_fake_sdk(monkeypatch, chat)

    provider = OpenRouterProvider(api_key="sk-test", models=["x"])
    with pytest.raises(OpenRouterAPIError, match="boom"):
        list(provider.chat("hi", streaming=False))


def test_chat_records_last_model_used_after_rotation(monkeypatch: pytest.MonkeyPatch):
    response = {"choices": [{"message": {"content": "ok"}}]}
    chat = FakeChat(events_or_response=response)
    install_fake_sdk(monkeypatch, chat)

    provider = OpenRouterProvider(
        api_key="sk-test",
        models=["a", "b"],
        rotate_models=True,
    )
    list(provider.chat("first", streaming=False))
    assert provider.last_model_used == "a"
    list(provider.chat("second", streaming=False))
    assert provider.last_model_used == "b"


def test_chat_passes_attribution_headers_to_sdk(monkeypatch: pytest.MonkeyPatch):
    chat = FakeChat(events_or_response={"choices": [{"message": {"content": "ok"}}]})
    sdk = install_fake_sdk(monkeypatch, chat)

    provider = OpenRouterProvider(
        api_key="sk-test",
        models=["x"],
        http_referer="https://example.com",
        x_title="tuochat",
    )
    list(provider.chat("hi", streaming=False))
    assert sdk.constructor_kwargs == {
        "api_key": "sk-test",
        "http_referer": "https://example.com",
        "x_open_router_title": "tuochat",
    }


# ---------------------------------------------------------------------------
# Lazy SDK import behaviour
# ---------------------------------------------------------------------------


def test_import_openrouter_sdk_raises_friendly_error_when_missing(monkeypatch: pytest.MonkeyPatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openrouter":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(OpenRouterUnavailableError, match="pip install"):
        openrouter_module.import_openrouter_sdk()
