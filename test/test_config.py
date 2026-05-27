"""Tests for configuration loading."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tuochat.config import (
    TuochatConfig,
    config_dir,
    data_dir,
    default_gitlab_user_agent,
    load_config,
    load_dotenv,
    log_dir,
    normalize_gitlab_host,
    parse_env_line,
    render_config,
    write_default_config,
)


def test_default_config():
    """Test that default config has sensible values."""
    cfg = TuochatConfig()
    assert cfg.gitlab.host == ""
    assert cfg.gitlab.token == ""
    assert cfg.gitlab.token_type == "pat"
    assert cfg.gitlab.user_agent == default_gitlab_user_agent()
    assert cfg.chat.platform_origin == "tuochat"
    assert cfg.chat.timeout == 120
    assert cfg.chat.websocket_welcome_timeout == 20
    assert cfg.chat.websocket_subscription_timeout == 20
    assert cfg.chat.response_footer_warning_enabled is False
    assert cfg.chat.no_write is False
    assert cfg.chat.safety_check_extension_for_executable_files is True
    assert cfg.features.startup_audit is False


def test_load_config_reads_no_write_flag(tmp_path):
    """Test loading the no_write chat setting from TOML."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("[chat]\nno_write = true\n", encoding="utf-8")
    cfg = load_config(str(config_file))
    assert cfg.chat.no_write is True


def test_load_config_reads_safety_check_extension_flag(tmp_path):
    """Test loading the safety .check chat setting from TOML."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("[chat]\nsafety_check_extension_for_executable_files = false\n", encoding="utf-8")
    cfg = load_config(str(config_file))
    assert cfg.chat.safety_check_extension_for_executable_files is False


def test_load_config_reads_startup_audit_feature_flag(tmp_path):
    """Test loading the startup audit feature flag from TOML."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("[features]\nstartup_audit = true\n", encoding="utf-8")
    cfg = load_config(str(config_file))
    assert cfg.features.startup_audit is True


def test_load_config_from_file(tmp_path):
    """Test loading config from a TOML file."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[gitlab]\nhost = "https://gitlab.example.com"\ntoken = "glpat-abc123"\n\n'
        'user_agent = "custom-agent/9.9"\n\n'
        "[chat]\n"
        "timeout = 60\n"
        "websocket_welcome_timeout = 25\n"
        "websocket_subscription_timeout = 35\n"
        "response_footer_warning_enabled = true\n"
    )
    with (
        patch("tuochat.config.load_dotenv"),
        patch.dict(os.environ, {}, clear=False) as env,
    ):
        env.pop("TUOCHAT_GITLAB_HOST", None)
        env.pop("TUOCHAT_GITLAB_TOKEN", None)
        cfg = load_config(str(config_file))
    assert cfg.gitlab.host == "https://gitlab.example.com"
    assert cfg.gitlab.token == "glpat-abc123"
    assert cfg.gitlab.user_agent == "custom-agent/9.9"
    assert cfg.chat.timeout == 60
    assert cfg.chat.websocket_welcome_timeout == 25
    assert cfg.chat.websocket_subscription_timeout == 35
    assert cfg.chat.response_footer_warning_enabled is True


def test_load_config_env_overrides(tmp_path):
    """Test that env vars override file settings."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[gitlab]\nhost = "https://file.com"\ntoken = "glpat-file"\n')

    with patch.dict(
        os.environ,
        {
            "TUOCHAT_GITLAB_HOST": "https://env.com",
            "TUOCHAT_GITLAB_TOKEN": "glpat-env",
            "TUOCHAT_GITLAB_USER_AGENT": "env-agent/2.0",
        },
    ):
        cfg = load_config(str(config_file))

    assert cfg.gitlab.host == "https://env.com"
    assert cfg.gitlab.token == "glpat-env"
    assert cfg.gitlab.user_agent == "env-agent/2.0"


def test_load_config_missing_file():
    """Test loading config with no file — uses defaults."""
    with (
        patch("tuochat.config.load_dotenv"),
        patch.dict(os.environ, {}, clear=False) as env,
    ):
        env.pop("TUOCHAT_GITLAB_HOST", None)
        env.pop("TUOCHAT_GITLAB_TOKEN", None)
        cfg = load_config("/nonexistent/path/config.toml")
    assert cfg.gitlab.host == ""
    assert cfg.gitlab.token == ""


def test_validate_missing_host():
    """Test validation catches missing host."""
    cfg = TuochatConfig()
    cfg.gitlab.token = "glpat-abc"
    warnings = cfg.validate()
    assert any("host" in w.lower() for w in warnings)


def test_validate_missing_token():
    """Test validation catches missing token."""
    cfg = TuochatConfig()
    cfg.gitlab.host = "https://gitlab.com"
    warnings = cfg.validate()
    assert any("token" in w.lower() for w in warnings)


def test_validate_valid_config():
    """Test validation passes with valid config."""
    cfg = TuochatConfig()
    cfg.gitlab.host = "https://gitlab.com"
    cfg.gitlab.token = "glpat-1234567890"
    warnings = cfg.validate()
    assert len(warnings) == 0


def test_redacted_config():
    """Test that redacted output hides the token."""
    cfg = TuochatConfig()
    cfg.gitlab.host = "https://gitlab.com"
    cfg.gitlab.token = "glpat-1234567890abcdef"
    redacted = cfg.redacted()
    assert "1234567890abcdef" not in str(redacted)
    assert "***" in redacted["gitlab"]["token"]
    assert redacted["gitlab"]["user_agent"] == default_gitlab_user_agent()


def test_host_trailing_slash_stripped(tmp_path):
    """Test that trailing slash is stripped from host."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[gitlab]\nhost = "https://gitlab.com/"\n')
    cfg = load_config(str(config_file))
    assert cfg.gitlab.host == "https://gitlab.com"


def test_write_default_config_creates_templates_dir(tmp_path):
    """Test starter config creation also creates the templates directory."""
    config_file = tmp_path / "config.toml"
    write_default_config(config_file)
    assert (tmp_path / "templates").is_dir()


def test_render_config_omits_legacy_age_personalization_field():
    """Rendered config should not write the removed age personalization field."""
    cfg = TuochatConfig()

    rendered = render_config(cfg)

    assert 'age = "' not in rendered
    assert f'user_agent = "{default_gitlab_user_agent()}"' in rendered
    assert "safety_check_extension_for_executable_files = true" in rendered
    assert "[features]" in rendered
    assert "startup_audit = false" in rendered


def test_load_config_ignores_legacy_age_personalization_field(tmp_path):
    """Legacy age personalization entries should load without affecting config shape."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[personalization]\n" "enabled = true\n" 'name = "Alice"\n' 'profession = "Engineer"\n' 'age = "30-39"\n',
        encoding="utf-8",
    )

    cfg = load_config(str(config_file))

    assert cfg.personalization.enabled is True
    assert cfg.personalization.name == "Alice"
    assert cfg.personalization.profession == "Engineer"
    assert not hasattr(cfg.personalization, "age")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gitlab.example.com", "https://gitlab.example.com"),
        (" https://gitlab.example.com/ ", "https://gitlab.example.com"),
        ("http://gitlab.example.com/group/project", "https://gitlab.example.com"),
    ],
)
def test_normalize_gitlab_host_returns_https_origin(raw, expected):
    """Test host normalization trims, upgrades to HTTPS, and drops paths."""
    assert normalize_gitlab_host(raw) == expected


def test_parse_env_line_supports_export_and_quotes():
    """Test .env parsing handles export prefixes and quoted values."""
    assert parse_env_line('export TUOCHAT_GITLAB_TOKEN="glpat-test"') == ("TUOCHAT_GITLAB_TOKEN", "glpat-test")


@pytest.mark.parametrize("line", ["", "   ", "# comment", "NOT_AN_ASSIGNMENT", "=missing_key"])
def test_parse_env_line_ignores_invalid_lines(line):
    """Test invalid .env lines are ignored cleanly."""
    assert parse_env_line(line) is None


def test_load_dotenv_respects_override_flag(tmp_path, monkeypatch):
    """Test dotenv loading preserves env vars unless override=True."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("TUOCHAT_GITLAB_HOST=https://file.example.com\n", encoding="utf-8")
    monkeypatch.setenv("TUOCHAT_GITLAB_HOST", "https://env.example.com")

    loaded_path = load_dotenv(dotenv)
    assert loaded_path == dotenv
    assert os.environ["TUOCHAT_GITLAB_HOST"] == "https://env.example.com"

    load_dotenv(dotenv, override=True)
    assert os.environ["TUOCHAT_GITLAB_HOST"] == "https://file.example.com"


def test_load_dotenv_returns_none_for_missing_file(tmp_path):
    """Test missing dotenv files are ignored."""
    assert load_dotenv(tmp_path / ".env") is None


def test_config_dir_prefers_explicit_env(monkeypatch, tmp_path):
    """Test config dir honors TUOCHAT_CONFIG_DIR when set."""
    monkeypatch.setenv("TUOCHAT_CONFIG_DIR", str(tmp_path))
    assert config_dir() == tmp_path


def test_config_dir_uses_windows_appdata(monkeypatch):
    """Test Windows config dir falls back to APPDATA."""
    monkeypatch.delenv("TUOCHAT_CONFIG_DIR", raising=False)
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")
    with patch("tuochat.config.sys.platform", "win32"):
        assert config_dir() == Path(r"C:\Users\me\AppData\Roaming") / "tuochat"


def test_data_dir_uses_linux_xdg(monkeypatch):
    """Test Linux data dir uses XDG_DATA_HOME."""
    monkeypatch.delenv("TUOCHAT_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-data")
    with patch("tuochat.config.sys.platform", "linux"):
        assert data_dir() == Path("/tmp/xdg-data") / "tuochat"


def test_log_dir_uses_macos_logs(monkeypatch):
    """Test macOS log dir uses Library/Logs instead of the data dir."""
    monkeypatch.delenv("TUOCHAT_DATA_DIR", raising=False)
    with (
        patch("tuochat.config.sys.platform", "darwin"),
        patch("tuochat.config.Path.home", return_value=Path("/Users/tester")),
    ):
        assert log_dir() == Path("/Users/tester/Library/Logs/tuochat")
