"""Unit tests for CLI bootstrap helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from tuochat.cli import bootstrap
from tuochat.cli.command_models import GlobalOptions
from tuochat.config import TuochatConfig
from tuochat.persistence import ConversationStore, NullConversationStore


def test_no_write_enabled():
    cfg = TuochatConfig()
    cfg.chat.no_write = True
    assert bootstrap.no_write_enabled(cfg) is True

    cfg.chat.no_write = False
    assert bootstrap.no_write_enabled(cfg) is False

    # Test with object that doesn't have chat
    assert bootstrap.no_write_enabled(cast(Any, object())) is False


def test_build_store_write_enabled(tmp_path):
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path
    cfg.chat.no_write = False

    with bootstrap.build_store(cfg) as store:
        assert isinstance(store, ConversationStore)


def test_build_store_no_write_enabled(tmp_path):
    cfg = TuochatConfig()
    cfg.data_dir = tmp_path
    cfg.chat.no_write = True

    with bootstrap.build_store(cfg) as store:
        assert isinstance(store, NullConversationStore)


def test_is_first_run_no_config_no_env(tmp_path):
    cfg = TuochatConfig()
    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    cfg.config_dir = config_dir
    config_path = config_dir / "nonexistent.toml"

    with patch.dict(os.environ, {"TUOCHAT_GITLAB_HOST": "", "TUOCHAT_GITLAB_TOKEN": ""}):
        assert bootstrap.is_first_run(cfg, config_path=str(config_path)) is True


def test_is_first_run_with_env(tmp_path):
    cfg = TuochatConfig()
    config_dir = tmp_path / "conf2"
    config_dir.mkdir()
    cfg.config_dir = config_dir
    config_path = config_dir / "nonexistent.toml"

    with patch.dict(os.environ, {"TUOCHAT_GITLAB_HOST": "https://gitlab.com", "TUOCHAT_GITLAB_TOKEN": "token"}):
        assert bootstrap.is_first_run(cfg, config_path=str(config_path)) is False


def test_is_first_run_with_openrouter_configuration(tmp_path):
    cfg = TuochatConfig()
    cfg.openrouter.api_key = "sk-or-test"
    cfg.openrouter.model = "openai/gpt-4.1-mini"
    config_path = tmp_path / "nonexistent.toml"

    with patch.dict(os.environ, {"TUOCHAT_GITLAB_HOST": "", "TUOCHAT_GITLAB_TOKEN": ""}):
        assert bootstrap.is_first_run(cfg, config_path=str(config_path)) is False


def test_is_first_run_with_existing_config_file(tmp_path):
    cfg = TuochatConfig()
    config_path = tmp_path / "config.toml"
    config_path.write_text("[gitlab]\nhost='https://gitlab.com'\n", encoding="utf-8")

    with patch.dict(os.environ, {"TUOCHAT_GITLAB_HOST": "", "TUOCHAT_GITLAB_TOKEN": ""}):
        assert bootstrap.is_first_run(cfg, config_path=str(config_path)) is False


def test_config_path_for():
    # From GlobalOptions.config_path
    options = MagicMock(spec=GlobalOptions)
    options.config_path = Path("path/to/config.toml")
    assert bootstrap.config_path_for(options) == Path("path/to/config.toml")

    # From generic object with 'config' attribute
    class Args:
        config = "other/path.toml"

    assert bootstrap.config_path_for(Args()) == Path("other/path.toml")

    # None
    assert bootstrap.config_path_for(object()) is None


def test_config_path_for_prefers_explicit_config_path():
    options = MagicMock(spec=GlobalOptions)
    options.config_path = Path("primary.toml")
    options.config = "secondary.toml"

    assert bootstrap.config_path_for(options) == Path("primary.toml")


def test_apply_global_overrides():
    cfg = TuochatConfig()
    options = GlobalOptions(no_banner=True, quiet=True, blind=False)

    bootstrap.apply_global_overrides(cfg, options)
    assert cfg.chat.no_banner is True
    assert cfg.chat.quiet is True
    assert cfg.chat.blind is False

    # Test blind mode overrides
    cfg = TuochatConfig()
    options = GlobalOptions(no_banner=False, quiet=False, blind=True)
    bootstrap.apply_global_overrides(cfg, options)
    assert cfg.chat.blind is True
    assert cfg.chat.no_banner is True


def test_apply_global_overrides_noop_returns_same_config():
    cfg = TuochatConfig()
    result = bootstrap.apply_global_overrides(cfg, GlobalOptions())

    assert result is cfg
    assert cfg.chat.no_banner is False
    assert cfg.chat.quiet is False
    assert cfg.chat.blind is False
