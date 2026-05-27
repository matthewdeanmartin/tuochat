from __future__ import annotations

from tuochat.context.validation import (
    find_high_entropy_strings,
    find_warn_phrases,
    is_high_entropy_string,
    looks_like_base64,
    shannon_entropy,
    validate_user_request,
)


class MockConfig:
    def __init__(self, warn_words_enabled=True, phrases=None):
        self.warn_words = MockWarnWords(warn_words_enabled, phrases or [])


class MockWarnWords:
    def __init__(self, enabled, phrases):
        self.enabled = enabled
        self.phrases = phrases


def test_shannon_entropy():
    assert shannon_entropy("") == 0.0
    # "aaaaa" has 0 entropy because it's only 1 character repeated
    assert shannon_entropy("aaaaa") == 0.0
    # "abcd" has 2 bits of entropy per character
    assert shannon_entropy("abcd") == 2.0


def test_looks_like_base64():
    # "SGVsbG8gd29ybGQgd2l0aCBzb21lIG1vcmUgdGV4dCB0byBtYWtlIGl0IGxvbmdlcg==" is "Hello world with some more text to make it longer"
    long_b64 = "SGVsbG8gd29ybGQgd2l0aCBzb21lIG1vcmUgdGV4dCB0byBtYWtlIGl0IGxvbmdlcg=="
    assert looks_like_base64(long_b64) is True
    assert looks_like_base64("too short") is False
    assert looks_like_base64("NotBase64!@#$%^&*") is False


def test_is_high_entropy_string():
    # Long, random looking string using only allowed chars A-Za-z0-9_+=/-
    # aB3_dE5+gH7/jK9=mN1-pQ3 is 23 chars
    assert is_high_entropy_string("aB3_dE5+gH7/jK9=mN1-pQ3") is True
    # Long, but not random looking (just 'a')
    assert is_high_entropy_string("a" * 30) is False
    # URL should be ignored
    assert is_high_entropy_string("https://example.com/very/long/url/that/looks/like/it/could/be/high/entropy") is False


def test_find_high_entropy_strings():
    text = "Here is a secret: aB3_dE5+gH7/jK9=mN1-pQ3 and another part."
    matches = find_high_entropy_strings(text)
    assert "aB3_dE5+gH7/jK9=mN1-pQ3" in matches


def test_find_warn_phrases():
    cfg = MockConfig(phrases=["INTERNAL_ONLY", "SECRET_PROJECT"])
    text = "This is an internal_only message about secret_project."
    matches = find_warn_phrases(text, cfg)
    assert "INTERNAL_ONLY" in matches
    assert "SECRET_PROJECT" in matches

    cfg.warn_words.enabled = False
    assert find_warn_phrases(text, cfg) == []


def test_validate_user_request():
    cfg = MockConfig(phrases=["warn"])

    # Valid request
    def prompt_yes(msg):
        return "y"

    assert (
        validate_user_request("This is a long enough request.", "This is a long enough request.", 1000, cfg, prompt_yes)
        is True
    )

    # Empty request
    assert validate_user_request("   ", "   ", 1000, cfg, prompt_yes) is False

    # Too short request, cancelled
    def prompt_no(msg):
        return "n"

    assert validate_user_request("Hi", "Hi", 1000, cfg, prompt_no) is False

    # Large request, confirmed
    assert validate_user_request("Long enough", "a" * 1001, 1000, cfg, prompt_yes) is True

    # Warn words, confirmed
    assert (
        validate_user_request("Long enough with warn word", "Long enough with warn word", 1000, cfg, prompt_yes) is True
    )


def test_validate_user_request_non_interactive_proceeds_past_size_limit(capsys):
    """In non-interactive mode, an oversized request warns to stderr and returns True."""
    cfg = MockConfig()

    def prompt_fn(msg):
        raise AssertionError("prompt_fn should not be called in non-interactive mode")

    result = validate_user_request("Long enough", "a" * 50001, 50000, cfg, prompt_fn, non_interactive=True)

    assert result is True
    captured = capsys.readouterr()
    assert "Warning" in captured.err
    assert "50001" in captured.err
