"""``tuochat auth`` subcommands: login, status, logout.

This is the interactive front door for credential management. The
first-run wizard calls into the same helpers so the experience is
identical whether you are running ``tuochat`` for the very first time
or rotating a credential later.
"""

# pylint: disable=import-outside-toplevel
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from tuochat.cli.prompts import prompt_bool, prompt_input, prompt_nonempty, prompt_text
from tuochat.config import default_gitlab_user_agent, normalize_gitlab_host, save_config
from tuochat.provider.oauth import (
    DEFAULT_REDIRECT,
    DEFAULT_SCOPES,
    OAuthClient,
    OAuthError,
    refresh_access_token,
    run_authorization_flow,
)
from tuochat.security.credentials import (
    StoredCredentials,
    delete_from_keyring,
    keyring_available,
    load_credentials,
    load_from_keyring,
    save_to_keyring,
    store_credentials,
)

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

logger = logging.getLogger("tuochat.cli.auth")
PAT_TOKEN_TYPE = "pat"


def env_oauth_defaults() -> dict[str, str]:
    """Read TUOCHAT_OAUTH_* environment variables into a defaults dict."""
    return {
        "client_id": os.environ.get("TUOCHAT_OAUTH_APP_ID", ""),
        "client_secret": os.environ.get("TUOCHAT_OAUTH_SECRET", ""),
        "redirect_uri": os.environ.get("TUOCHAT_OAUTH_REDIRECT", DEFAULT_REDIRECT),
    }


def resolve_oauth_client(cfg: TuochatConfig, *, prompt_for_missing: bool) -> OAuthClient:
    """Build an :class:`OAuthClient` from env vars, the keyring, or prompts.

    Lookup order for each field:

        1. Environment variables (TUOCHAT_OAUTH_APP_ID / TUOCHAT_OAUTH_SECRET / TUOCHAT_OAUTH_REDIRECT).
        2. Existing keyring entry for the configured host.
        3. Interactive prompt (only when ``prompt_for_missing`` is True).
    """
    defaults = env_oauth_defaults()
    stored = load_from_keyring(cfg.gitlab.host) if cfg.gitlab.host else None
    if stored is not None:
        if not defaults["client_id"]:
            defaults["client_id"] = stored.oauth_app_id
        if not defaults["client_secret"]:
            defaults["client_secret"] = stored.oauth_app_secret
        if not defaults["redirect_uri"] and stored.oauth_redirect:
            defaults["redirect_uri"] = stored.oauth_redirect

    client_id = defaults["client_id"]
    client_secret = defaults["client_secret"]
    redirect = defaults["redirect_uri"] or DEFAULT_REDIRECT

    if prompt_for_missing:
        if not client_id:
            client_id = prompt_nonempty("OAuth Application ID: ")
        if not client_secret:
            client_secret = prompt_nonempty("OAuth Application Secret (input hidden): ", secret=True)
        redirect = (
            prompt_text(
                f"OAuth redirect URI [{redirect}]: ",
                default=redirect,
            )
            or redirect
        )

    if not client_id or not client_secret:
        raise OAuthError(
            "Missing OAuth client id or secret. Set TUOCHAT_OAUTH_APP_ID and "
            "TUOCHAT_OAUTH_SECRET, or run `tuochat auth login` interactively."
        )

    return OAuthClient(
        host=cfg.gitlab.host,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect,
        scopes=DEFAULT_SCOPES,
        user_agent=getattr(cfg.gitlab, "user_agent", default_gitlab_user_agent()),
    )


def offer_storage_choice(*, default_keyring: bool = True) -> bool:
    """Ask the user where to put new credentials and return ``prefer_keyring``."""
    if not keyring_available():
        print("(no OS secret store detected on this machine -- credentials will go in the central config file)")
        return False
    label = "Store credentials in the OS secret store (recommended)?"
    return prompt_bool(label, default=default_keyring)


def collect_pat(cfg: TuochatConfig) -> StoredCredentials:
    """Prompt the user for a PAT and return a :class:`StoredCredentials`."""
    print("Create a personal access token at:")
    print(f"  {cfg.gitlab.host or 'https://gitlab.com'}/-/user_settings/personal_access_tokens")
    print("Recommended scopes: api (or, for least privilege, ai_features + read_api + read_user + read_repository).")
    token = prompt_nonempty("Personal access token (input hidden): ", secret=True)
    return StoredCredentials(
        host=cfg.gitlab.host,
        token_type=PAT_TOKEN_TYPE,
        access_token=token,
    )


def run_oauth_login(cfg: TuochatConfig) -> StoredCredentials:
    """Run the full OAuth flow and return the resulting credentials."""
    client = resolve_oauth_client(cfg, prompt_for_missing=True)
    print(f"Starting GitLab OAuth flow for {client.host} as application {client.client_id[:8]}...")
    return run_authorization_flow(client)


def ensure_host(cfg: TuochatConfig) -> None:
    """Make sure ``cfg.gitlab.host`` is populated, prompting if necessary."""
    if cfg.gitlab.host:
        return
    raw = (
        prompt_text(
            "GitLab server URL [https://gitlab.com]: ",
            default="https://gitlab.com",
        )
        or "https://gitlab.com"
    )
    cfg.gitlab.host = normalize_gitlab_host(raw)
    save_config(cfg)


def interactive_login(cfg: TuochatConfig) -> StoredCredentials:
    """Pick PAT vs OAuth, gather credentials, persist them, and return them."""
    ensure_host(cfg)

    print()
    print("Tuochat credential setup")
    print(f"  Host: {cfg.gitlab.host}")
    print()
    print("Pick how you want to authenticate to GitLab:")
    print("  [1] Personal access token (PAT) - quick, manual rotation")
    print("  [2] OAuth (browser sign-in) - refresh tokens, no manual rotation")
    while True:
        raw = prompt_input("auth> ").strip()
        if raw in {"1", "pat", "p"}:
            creds = collect_pat(cfg)
            break
        if raw in {"2", "oauth", "o"}:
            creds = run_oauth_login(cfg)
            break
        print("Please enter 1 or 2.")

    prefer_keyring = offer_storage_choice()
    where = store_credentials(cfg, creds, prefer_keyring=prefer_keyring)
    print(f"Credentials saved to: {where}")
    return creds


def run_login(cfg: TuochatConfig) -> int:
    """Handle ``tuochat auth login``."""
    try:
        interactive_login(cfg)
    except OAuthError as exc:
        print(f"OAuth failed: {exc}")
        return 1
    return 0


def run_status(cfg: TuochatConfig) -> int:
    """Handle ``tuochat auth status``."""
    print(f"Host: {cfg.gitlab.host or '(unset)'}")
    print(f"Keyring backend available: {keyring_available()}")
    creds = load_credentials(cfg)
    if creds is None or not creds.access_token:
        print("No credentials on file. Run `tuochat auth login` to set them up.")
        return 1
    print(f"Token type: {creds.token_type}")
    if creds.is_oauth():
        if creds.expires_at:
            import time as time_mod  # noqa: PLC0415

            remaining = int(creds.expires_at - time_mod.time())
            print(f"Access token expires in: {remaining}s")
        else:
            print("Access token expiry: unknown")
        print(f"Refresh token on file: {'yes' if creds.refresh_token else 'no'}")
        print(f"OAuth scopes: {' '.join(creds.scopes) if creds.scopes else '(unknown)'}")
    print("Storage:", "keyring" if load_from_keyring(cfg.gitlab.host) else "config file")
    return 0


def run_logout(cfg: TuochatConfig) -> int:
    """Handle ``tuochat auth logout`` -- wipe credentials for the active host."""
    host = cfg.gitlab.host
    if not host:
        print("No host configured; nothing to clear.")
        return 0
    removed_keyring = delete_from_keyring(host)
    cleared_config = bool(cfg.gitlab.token)
    cfg.gitlab.token = ""
    save_config(cfg)
    print(f"Removed from keyring: {removed_keyring}")
    print(f"Cleared config token: {cleared_config}")
    return 0


def run_refresh(cfg: TuochatConfig) -> int:
    """Handle ``tuochat auth refresh`` -- exchange the refresh token for a new access token."""
    creds = load_credentials(cfg)
    if creds is None or not creds.is_oauth() or not creds.refresh_token:
        print("No OAuth refresh token on file; run `tuochat auth login` instead.")
        return 1
    try:
        client = resolve_oauth_client(cfg, prompt_for_missing=False)
    except OAuthError as exc:
        print(f"Cannot refresh: {exc}")
        return 1
    try:
        fresh = refresh_access_token(client, creds.refresh_token)
    except OAuthError as exc:
        print(f"Refresh failed: {exc}")
        return 1
    if save_to_keyring(fresh):
        print("Refreshed access token saved to OS secret store.")
    else:
        cfg.gitlab.token = fresh.access_token
        cfg.gitlab.token_type = "oauth"
        save_config(cfg)
        print(f"Refreshed access token saved to: {cfg.config_file}")
    return 0


__all__ = [
    "collect_pat",
    "ensure_host",
    "env_oauth_defaults",
    "interactive_login",
    "offer_storage_choice",
    "resolve_oauth_client",
    "run_login",
    "run_logout",
    "run_oauth_login",
    "run_refresh",
    "run_status",
]
