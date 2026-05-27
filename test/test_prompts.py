"""Unit tests for CLI prompt helpers."""

from __future__ import annotations

import builtins

from tuochat.cli import prompts
from tuochat.cli.io import prompt_handler


def test_prompt_nonempty_retries_until_trimmed_value(monkeypatch, capsys):
    answers = iter(["   ", "  hello  "])
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: next(answers))

    result = prompts.prompt_nonempty("Name: ")

    assert result == "hello"
    assert "A value is required." in capsys.readouterr().err


def test_prompt_nonempty_returns_default_on_blank(monkeypatch):
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: "   ")

    assert prompts.prompt_nonempty("Name: ", default="fallback") == "fallback"


def test_prompt_nonempty_uses_secret_prompt(monkeypatch):
    monkeypatch.setattr(prompts, "read_prompt", lambda prompt, secret=False: "  secret  ")

    assert prompts.prompt_nonempty("Secret: ", secret=True) == "secret"


def test_prompt_text_returns_default_or_empty_string(monkeypatch):
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: "   ")
    assert prompts.prompt_text("Optional: ", default="fallback") == "fallback"

    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: "   ")
    assert prompts.prompt_text("Optional: ") == ""


def test_prompt_text_uses_secret_prompt(monkeypatch):
    monkeypatch.setattr(prompts, "read_prompt", lambda prompt, secret=False: "  token  ")

    assert prompts.prompt_text("Token: ", secret=True) == "token"


def test_readprompt_input_handles_eof(monkeypatch, capsys):
    def raise_eof(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)

    assert prompts.readprompt_input("Prompt: ") == ("", True)
    assert capsys.readouterr().out == "\n"


def test_readprompt_input_strips_inline_eof_and_warns(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda prompt: "hello\x1aignored")

    assert prompts.readprompt_input("Prompt: ") == ("hello", True)
    captured = capsys.readouterr()
    assert captured.out == "\n"
    assert "stripped text that appeared after Ctrl+Z" in captured.err


def test_prompt_input_returns_only_the_value(monkeypatch):
    monkeypatch.setattr(prompts, "readprompt_input", lambda prompt: ("value", True))

    assert prompts.prompt_input("Prompt: ") == "value"


def test_prompt_bool_reprompts_until_valid(monkeypatch, capsys):
    answers = iter(["maybe", "YES"])
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: next(answers))

    assert prompts.prompt_bool("Proceed?", default=False) is True
    assert "Please answer y or n." in capsys.readouterr().err


def test_prompt_bool_returns_default_on_blank(monkeypatch):
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: "   ")

    assert prompts.prompt_bool("Proceed?", default=True) is True


def test_prompt_int_reprompts_until_minimum(monkeypatch, capsys):
    answers = iter(["-1", "abc", "5"])
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: next(answers))

    assert prompts.prompt_int("Count", default=2, minimum=3) == 5
    assert capsys.readouterr().err.count("Enter an integer >= 3.") == 2


def test_prompt_int_returns_default_on_blank(monkeypatch):
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: "")

    assert prompts.prompt_int("Count", default=4, minimum=1) == 4


def test_dedupe_preserve_order_strips_and_drops_empty_items():
    assert prompts.dedupe_preserve_order([" one ", "two", "", "one", " two ", "three "]) == ["one", "two", "three"]


def test_prompt_csv_list_returns_copy_of_default_on_blank(monkeypatch):
    default = ["alpha", "beta"]
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: "   ")

    result = prompts.prompt_csv_list("Items", default=default)

    assert result == default
    assert result is not default


def test_prompt_csv_list_dedupes_values(monkeypatch):
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: " alpha, beta, alpha, , gamma ")

    assert prompts.prompt_csv_list("Items") == ["alpha", "beta", "gamma"]


def test_prompt_pick_many_supports_default_all_deduping_and_validation(monkeypatch, capsys):
    answers = iter(["2, 2, 3", "bad", "all"])
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: next(answers))

    assert prompts.prompt_pick_many("Pick:", ["All", "one", "two"]) == ["one", "two"]
    assert prompts.prompt_pick_many("Pick:", ["All", "one", "two"]) == ["All"]
    assert "Use one or more numbers from the list, or `all`." in capsys.readouterr().err


def test_prompt_pick_many_returns_default_on_blank(monkeypatch):
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: "")

    assert prompts.prompt_pick_many("Pick:", ["one", "two"], default=["two"]) == ["two"]


def test_submit_key_hint_matches_platform(monkeypatch):
    monkeypatch.setattr(prompts.sys, "platform", "win32")
    assert prompts.submit_key_hint() == "Ctrl+Z, Enter"

    monkeypatch.setattr(prompts.sys, "platform", "linux")
    assert prompts.submit_key_hint() == "Ctrl+D"


def test_split_inline_eof_marker_handles_present_and_missing_marker():
    assert prompts.split_inline_eof_marker("plain text") == ("plain text", False, False)
    assert prompts.split_inline_eof_marker("hello\x1aworld") == ("hello", True, True)
    assert prompts.split_inline_eof_marker("hello\x1a") == ("hello", True, False)


def test_read_user_message_returns_exit_on_immediate_eof(monkeypatch, capsys):
    def raise_eof(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)

    assert prompts.read_user_message() == (None, True)
    assert capsys.readouterr().out == "\n"


def test_read_user_message_collects_multiline_input_until_eof(monkeypatch, capsys):
    entries = iter(["first line", "second line"])

    def fake_input(prompt: str) -> str:
        try:
            return next(entries)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(builtins, "input", fake_input)

    assert prompts.read_user_message(quiet=True) == ("first line\nsecond line", False)
    assert capsys.readouterr().out == "\n"


def test_read_user_message_cancels_current_draft_on_ctrl_c(monkeypatch, capsys):
    entries = iter(["first line"])

    def fake_input(prompt: str) -> str:
        try:
            return next(entries)
        except StopIteration as exc:
            raise KeyboardInterrupt from exc

    monkeypatch.setattr(builtins, "input", fake_input)

    assert prompts.read_user_message(quiet=True) == (None, False)
    captured = capsys.readouterr()
    assert captured.out == "\n"
    assert prompts.MESSAGE_CANCELLED_HINT in captured.err


def test_read_user_message_handles_inline_eof_and_warning(monkeypatch, capsys):
    entries = iter(["first line", "second line\x1aignored"])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(entries))

    assert prompts.read_user_message() == ("first line\nsecond line", False)
    captured = capsys.readouterr()
    assert captured.out == "\n"
    assert "stripped text that appeared after Ctrl+Z" in captured.err


def test_prompt_missing_slash_command_supports_execute_send_and_cancel(monkeypatch, capsys):
    answers = iter(["wait", "", "send", "cancel"])
    monkeypatch.setattr(prompts, "prompt_input", lambda prompt: next(answers))

    assert prompts.prompt_missing_slash_command("help") is True
    assert prompts.prompt_missing_slash_command("help") is False
    assert prompts.prompt_missing_slash_command("help") is None
    assert "Please choose E to execute or S to send." in capsys.readouterr().err


def test_prompt_input_uses_installed_prompt_handler():
    with prompt_handler(lambda prompt, secret=False: "hooked"):
        assert prompts.prompt_input("Prompt: ") == "hooked"
