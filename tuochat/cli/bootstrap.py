"""CLI bootstrap helpers that stay independent of argparse."""

# pylint: disable=import-outside-toplevel
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tuochat.cli.command_models import GlobalOptions
    from tuochat.config import TuochatConfig
    from tuochat.persistence import ConversationStore, NullConversationStore
    from tuochat.provider.duo import DuoProvider


def build_provider(cfg: TuochatConfig, *, timeout_override: int | None = None) -> DuoProvider:
    """Construct a Duo provider from config, auto-detecting proxy on first call."""
    # Provider imports are expensive and only needed for chat-capable commands.
    from tuochat.provider.duo import DuoProvider  # noqa: E402
    from tuochat.provider.proxy import get_session_proxy  # noqa: E402

    effective_timeout = timeout_override if timeout_override is not None else cfg.chat.timeout

    opener = None
    proxy_host_port = None
    if cfg.gitlab.host:
        proxy_result = get_session_proxy(cfg.gitlab.host)
        opener = proxy_result.build_opener()
        proxy_host_port = proxy_result.proxy_host_port()

    return DuoProvider(
        host=cfg.gitlab.host,
        token=cfg.gitlab.token,
        token_type=cfg.gitlab.token_type,
        platform_origin=cfg.chat.platform_origin,
        user_agent=getattr(cfg.gitlab, "user_agent", None),
        timeout=effective_timeout,
        websocket_welcome_timeout=cfg.chat.websocket_welcome_timeout,
        websocket_subscription_timeout=cfg.chat.websocket_subscription_timeout,
        opener=opener,
        proxy_host_port=proxy_host_port,
    )


def no_write_enabled(cfg: TuochatConfig) -> bool:
    """Return whether local writes are disabled in the config-like object."""
    return bool(getattr(getattr(cfg, "chat", None), "no_write", False))


def build_store(cfg: TuochatConfig) -> ConversationStore | NullConversationStore:
    """Build the appropriate conversation store for the current config."""
    # Delay persistence imports for commands that only inspect config or help text.
    from tuochat.persistence import ConversationStore, NullConversationStore  # noqa: E402

    if no_write_enabled(cfg):
        return NullConversationStore(cfg.db_path)
    return ConversationStore(cfg.db_path)


def is_first_run(cfg: TuochatConfig, *, config_path: str | None = None) -> bool:
    """Return True when no usable config or env-backed credentials exist yet."""
    has_env_credentials = bool(os.environ.get("TUOCHAT_GITLAB_HOST") and os.environ.get("TUOCHAT_GITLAB_TOKEN"))
    target = Path(config_path).expanduser() if config_path else cfg.config_file
    return not target.is_file() and not has_env_credentials and not cfg.gitlab.host and not cfg.gitlab.token


def maybe_run_first_run_setup(cfg: TuochatConfig, *, config_path: str | None = None) -> TuochatConfig:
    """Offer and run interactive setup on first use."""
    # Guided setup helpers are only needed for first-run and upgrade flows.
    from tuochat.cli.prompts import prompt_input  # noqa: E402
    from tuochat.cli.setup import config_requires_upgrade, run_init_wizard  # noqa: E402

    target = Path(config_path).expanduser() if config_path else cfg.config_file
    if is_first_run(cfg, config_path=config_path):
        print("No Tuochat config was found, so first-run setup is starting now.")
        path = run_init_wizard(config_path=target, force=True)
    elif config_requires_upgrade(target):
        print(
            "Your config is missing newer setup fields for personalization, document classifications, or generated-file headers."
        )
        choice = prompt_input("Run guided setup now to update it in place? [Y/n] ").strip().lower()
        if choice in {"", "y", "yes"}:
            path = run_init_wizard(config_path=target, force=True)
        else:
            return cfg
    else:
        return cfg

    from tuochat.config import load_config

    return load_config(str(path))


def config_path_for(options: Any) -> Path | None:
    """Return the normalized config path from global options."""
    raw = getattr(options, "config_path", None)
    if raw is None:
        raw = getattr(options, "config", None)
    return Path(raw).expanduser() if raw is not None else None


def apply_global_overrides(cfg: TuochatConfig, options: GlobalOptions) -> TuochatConfig:
    """Apply global CLI flags to the loaded config object."""
    if options.no_banner:
        cfg.chat.no_banner = True
    if options.quiet:
        cfg.chat.quiet = True
    if options.blind:
        cfg.chat.blind = True
        cfg.chat.no_banner = True
    return cfg
