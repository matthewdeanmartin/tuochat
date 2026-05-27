"""``tuochat openrouter`` subcommands: login, status, logout.

Handles storing the OpenRouter API key in the OS secret store with the
same fallback-to-config pattern the GitLab credential flow uses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tuochat.cli.prompts import prompt_nonempty
from tuochat.config import save_config
from tuochat.security.credentials import keyring_available
from tuochat.security.openrouter_secret import delete_api_key, load_api_key, save_api_key

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

logger = logging.getLogger("tuochat.cli.openrouter_auth")


def run_login(cfg: TuochatConfig) -> int:
    """Prompt for an OpenRouter API key and persist it."""
    print()
    print("OpenRouter credential setup")
    print("Get an API key from https://openrouter.ai/keys")
    api_key = prompt_nonempty("OpenRouter API key (input hidden): ", secret=True)

    if keyring_available() and save_api_key(api_key):
        cfg.openrouter.api_key = ""
        save_config(cfg)
        print("API key saved to the OS secret store.")
    else:
        cfg.openrouter.api_key = api_key
        save_config(cfg)
        print(f"API key saved to: {cfg.config_file}")
        print("(no OS secret store available — key was written to the config file)")
    return 0


def run_status(cfg: TuochatConfig) -> int:
    """Report whether an OpenRouter API key is on file."""
    print(f"Keyring backend available: {keyring_available()}")
    keyring_value = load_api_key()
    has_keyring = bool(keyring_value)
    has_config = bool(cfg.openrouter.api_key) and not has_keyring
    has_env = bool(cfg.openrouter.api_key) and has_keyring  # env can override config when not in keyring
    if not (has_keyring or cfg.openrouter.api_key):
        print("No OpenRouter API key on file. Run `tuochat openrouter login` to set one.")
        return 1
    if keyring_value:
        print(f"API key in keyring: yes (***{keyring_value[-4:]})")
    else:
        print("API key in keyring: no")
    if cfg.openrouter.api_key and not has_keyring:
        print(f"API key in config/env: yes (***{cfg.openrouter.api_key[-4:]})")
    print(f"Default model: {cfg.openrouter.model or '(none)'}")
    models = cfg.openrouter.effective_models()
    if models:
        print(f"Rotation list: {', '.join(models)}")
        print(f"Rotate models: {'on' if cfg.openrouter.rotate_models else 'off'}")
    _ = has_config, has_env  # avoid unused-name complaint
    return 0


def run_logout(cfg: TuochatConfig) -> int:
    """Wipe the stored OpenRouter API key."""
    removed_keyring = delete_api_key()
    cleared_config = bool(cfg.openrouter.api_key)
    cfg.openrouter.api_key = ""
    save_config(cfg)
    print(f"Removed from keyring: {removed_keyring}")
    print(f"Cleared config api_key: {cleared_config}")
    return 0


__all__ = ["run_login", "run_logout", "run_status"]
