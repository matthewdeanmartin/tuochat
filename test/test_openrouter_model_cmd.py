"""Dedicated tests for session-level OpenRouter model commands."""

from __future__ import annotations

from types import SimpleNamespace

from tuochat.cli.commands.openrouter_model_cmd import handle_openrouter_model_command
from tuochat.config import TuochatConfig


def make_state():
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-or-secret"
    cfg.openrouter.model = "openai/gpt-4.1-mini"
    cfg.openrouter.models = ["openai/gpt-4.1-mini", "openrouter/free"]
    return SimpleNamespace(cfg=cfg, active_openrouter_model=None)


def test_status_masks_key_and_lists_rotation_models(capsys):
    state = make_state()

    handle_openrouter_model_command("/openrouter-model", "status", state)

    output = capsys.readouterr().out
    assert "***cret" in output
    assert "1. openai/gpt-4.1-mini" in output
    assert "2. openrouter/free" in output
    assert "sk-or-secret" not in output


def test_set_list_and_clear_session_override(capsys):
    state = make_state()

    handle_openrouter_model_command("/openrouter-model", "set anthropic/claude-sonnet-4", state)
    assert state.active_openrouter_model == "anthropic/claude-sonnet-4"

    handle_openrouter_model_command("/openrouter-model", "list", state)
    handle_openrouter_model_command("/openrouter-model", "clear", state)
    assert state.active_openrouter_model is None
    assert "Cleared OpenRouter model override" in capsys.readouterr().out


def test_rotate_accepts_on_off_and_toggle(capsys):
    state = make_state()

    handle_openrouter_model_command("/openrouter-model", "rotate on", state)
    assert state.cfg.openrouter.rotate_models is True
    handle_openrouter_model_command("/openrouter-model", "rotate off", state)
    assert state.cfg.openrouter.rotate_models is False
    handle_openrouter_model_command("/openrouter-model", "rotate", state)
    assert state.cfg.openrouter.rotate_models is True
    assert "OpenRouter rotation: on" in capsys.readouterr().out


def test_invalid_rotate_value_prints_usage_without_changing_state(capsys):
    state = make_state()
    state.cfg.openrouter.rotate_models = False

    handle_openrouter_model_command("/openrouter-model", "rotate perhaps", state)

    assert state.cfg.openrouter.rotate_models is False
    assert "Usage: /openrouter-model rotate [on|off]" in capsys.readouterr().err


def test_unknown_subcommand_prints_help(capsys):
    state = make_state()

    handle_openrouter_model_command("/openrouter-model", "wat", state)

    assert "OpenRouter model commands:" in capsys.readouterr().out
