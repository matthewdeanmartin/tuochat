"""Tests for the OpenRouter config slice and env-var loading."""

from __future__ import annotations

import pytest

from tuochat.config import (
    DEFAULT_OPENROUTER_BASE_URL,
    OpenRouterConfig,
    TuochatConfig,
    apply_toml,
    load_config,
    render_config,
    save_config,
)


def test_openrouter_config_defaults():
    cfg = OpenRouterConfig()
    assert cfg.api_key == ""
    assert cfg.base_url == DEFAULT_OPENROUTER_BASE_URL
    assert cfg.model == ""
    assert cfg.models == []
    assert cfg.rotate_models is False


def test_effective_models_prefers_explicit_list():
    cfg = OpenRouterConfig(model="solo", models=["a", "b"])
    assert cfg.effective_models() == ["a", "b"]


def test_effective_models_falls_back_to_single_model():
    cfg = OpenRouterConfig(model="solo", models=[])
    assert cfg.effective_models() == ["solo"]


def test_effective_models_empty_when_nothing_configured():
    assert OpenRouterConfig().effective_models() == []


def test_load_config_picks_up_openrouter_env_vars(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)  # avoid project .env leaking into the test
    monkeypatch.setenv("TUOCHAT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("OPENROUTER_MODELS", "openai/gpt-4.1-mini, openrouter/free")
    monkeypatch.setenv("OPENROUTER_ROTATE_MODELS", "true")
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.invalid")
    monkeypatch.setenv("OPENROUTER_X_TITLE", "tuochat-test")

    cfg = load_config()
    assert cfg.openrouter.api_key == "sk-or-test"
    assert cfg.openrouter.base_url == "https://example.invalid/v1"
    assert cfg.openrouter.model == "openai/gpt-4.1-mini"
    assert cfg.openrouter.models == ["openai/gpt-4.1-mini", "openrouter/free"]
    assert cfg.openrouter.rotate_models is True
    assert cfg.openrouter.http_referer == "https://example.invalid"
    assert cfg.openrouter.x_title == "tuochat-test"


def test_rotate_models_env_accepts_falsey_values(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TUOCHAT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_ROTATE_MODELS", "off")
    cfg = load_config()
    assert cfg.openrouter.rotate_models is False


def test_render_then_apply_round_trips_openrouter(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)  # avoid project .env leaking into the test
    # Avoid env leakage from the calling shell
    for key in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_MODEL",
        "OPENROUTER_MODELS",
        "OPENROUTER_ROTATE_MODELS",
        "OPENROUTER_HTTP_REFERER",
        "OPENROUTER_X_TITLE",
    ):
        monkeypatch.delenv(key, raising=False)
    # Bypass any real keyring entry stored on the developer's machine
    from tuochat.security import openrouter_secret as _openrouter_secret

    monkeypatch.setattr(_openrouter_secret, "load_api_key", lambda: None)

    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-roundtrip"
    cfg.openrouter.model = "openai/gpt-4.1-mini"
    cfg.openrouter.models = ["openai/gpt-4.1-mini", "openrouter/free"]
    cfg.openrouter.rotate_models = True
    cfg.openrouter.http_referer = "https://example.invalid"
    cfg.openrouter.x_title = "tuochat-test"

    text = render_config(cfg)
    assert "[openrouter]" in text
    assert "sk-roundtrip" in text
    assert "rotate_models = true" in text

    # Re-parse via the toml loader path that apply_toml expects
    import sys

    if sys.version_info >= (3, 11):
        import tomllib as toml_loader
    else:
        import tomli as toml_loader  # type: ignore[no-redef]
    parsed = toml_loader.loads(text)
    fresh = TuochatConfig()
    apply_toml(fresh, parsed)
    assert fresh.openrouter.api_key == "sk-roundtrip"
    assert fresh.openrouter.models == ["openai/gpt-4.1-mini", "openrouter/free"]
    assert fresh.openrouter.rotate_models is True
    assert fresh.openrouter.http_referer == "https://example.invalid"

    # Also exercise save_config -> load_config end-to-end
    monkeypatch.setenv("TUOCHAT_CONFIG_DIR", str(tmp_path))
    save_config(fresh, tmp_path / "config.toml")
    monkeypatch.setenv("TUOCHAT_CONFIG", str(tmp_path / "config.toml"))
    reloaded = load_config(str(tmp_path / "config.toml"))
    assert reloaded.openrouter.api_key == "sk-roundtrip"
    assert reloaded.openrouter.rotate_models is True
