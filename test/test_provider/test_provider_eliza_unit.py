"""Unit tests for the Eliza provider."""

from __future__ import annotations

from tuochat.provider.eliza import ElizaProvider, reflect


def test_reflect():
    assert reflect("I am happy") == "you are happy"
    assert reflect("you are sad") == "I am sad"
    assert reflect("my car is red") == "your car is red"
    assert reflect("your house is big") == "my house is big"


def test_eliza_respond_greeting():
    eliza = ElizaProvider()
    response = eliza.respond("hello")
    assert any(greeting in response for greeting in ["Hey", "Hi", "Hello"])


def test_eliza_respond_how_are_you():
    eliza = ElizaProvider()
    response = eliza.respond("how are you?")
    assert any(phrase in response.lower() for phrase in ["doing well", "pretty good", "all good"])


def test_eliza_chat_streaming():
    eliza = ElizaProvider()
    responses = list(eliza.chat(MagicInput("hello"), streaming=True))
    assert len(responses) > 0
    full_response = "".join(responses)
    assert any(greeting in full_response for greeting in ["Hey", "Hi", "Hello"])


def test_eliza_chat_non_streaming():
    eliza = ElizaProvider()
    responses = list(eliza.chat(MagicInput("hello"), streaming=False))
    assert len(responses) == 1
    assert any(greeting in responses[0] for greeting in ["Hey", "Hi", "Hello"])


class MagicInput:
    def __init__(self, text):
        self.text = text

    def strip(self):
        return self.text.strip()
