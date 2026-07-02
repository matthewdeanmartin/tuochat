"""Dedicated tests for OpenRouter credential commands."""

from __future__ import annotations

from tuochat.cli.commands import openrouter_auth_cmd
from tuochat.config import TuochatConfig


def test_login_saves_keyring_secret_and_clears_config(monkeypatch, capsys):
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "stale-config-key"
    saved_configs = []

    monkeypatch.setattr(openrouter_auth_cmd, "prompt_nonempty", lambda prompt, secret: "sk-or-keyring")
    monkeypatch.setattr(openrouter_auth_cmd, "keyring_available", lambda: True)
    monkeypatch.setattr(openrouter_auth_cmd, "save_api_key", lambda api_key: api_key == "sk-or-keyring")
    monkeypatch.setattr(openrouter_auth_cmd, "save_config", saved_configs.append)

    assert openrouter_auth_cmd.run_login(cfg) == 0
    assert cfg.openrouter.api_key == ""
    assert saved_configs == [cfg]
    assert "OS secret store" in capsys.readouterr().out


def test_login_falls_back_to_config_when_keyring_is_unavailable(monkeypatch, capsys):
    cfg = TuochatConfig()
    saved_configs = []

    monkeypatch.setattr(openrouter_auth_cmd, "prompt_nonempty", lambda prompt, secret: "sk-or-config")
    monkeypatch.setattr(openrouter_auth_cmd, "keyring_available", lambda: False)
    monkeypatch.setattr(openrouter_auth_cmd, "save_api_key", lambda api_key: False)
    monkeypatch.setattr(openrouter_auth_cmd, "save_config", saved_configs.append)

    assert openrouter_auth_cmd.run_login(cfg) == 0
    assert cfg.openrouter.api_key == "sk-or-config"
    assert saved_configs == [cfg]
    assert "key was written to the config file" in capsys.readouterr().out


def test_status_reports_missing_key(monkeypatch, capsys):
    cfg = TuochatConfig()
    monkeypatch.setattr(openrouter_auth_cmd, "keyring_available", lambda: True)
    monkeypatch.setattr(openrouter_auth_cmd, "load_api_key", lambda: None)

    assert openrouter_auth_cmd.run_status(cfg) == 1
    assert "No OpenRouter API key" in capsys.readouterr().out


def test_status_reports_models_and_masks_key(monkeypatch, capsys):
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-or-visible"
    cfg.openrouter.models = ["openai/gpt-4.1-mini", "openrouter/free"]
    cfg.openrouter.rotate_models = True
    monkeypatch.setattr(openrouter_auth_cmd, "keyring_available", lambda: False)
    monkeypatch.setattr(openrouter_auth_cmd, "load_api_key", lambda: None)

    assert openrouter_auth_cmd.run_status(cfg) == 0
    output = capsys.readouterr().out
    assert "***ible" in output
    assert "openai/gpt-4.1-mini, openrouter/free" in output
    assert "Rotate models: on" in output
    assert "sk-or-visible" not in output


def test_logout_removes_keyring_and_config_secrets(monkeypatch, capsys):
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-or-config"
    saved_configs = []
    monkeypatch.setattr(openrouter_auth_cmd, "delete_api_key", lambda: True)
    monkeypatch.setattr(openrouter_auth_cmd, "save_config", saved_configs.append)

    assert openrouter_auth_cmd.run_logout(cfg) == 0
    assert cfg.openrouter.api_key == ""
    assert saved_configs == [cfg]
    output = capsys.readouterr().out
    assert "Removed from keyring: True" in output
    assert "Cleared config api_key: True" in output
