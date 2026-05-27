"""Cross-platform credential storage for tuochat.

Tokens and OAuth client secrets live in the OS secret store via the
``keyring`` package: Windows Credential Manager on Windows, the macOS
Keychain on Darwin, and Secret Service / kwallet / libsecret on Linux.

When keyring is unavailable (headless Linux box without Secret Service,
locked-down environments, etc.) we fall back to the central tuochat
config file -- the same place a PAT lives today.

The set of secrets we store per host is small and stable:

    - access token (PAT or OAuth access token)
    - refresh token (OAuth only)
    - access token expiry (epoch seconds, OAuth only)
    - OAuth app id (the GitLab application id, not really secret but
      kept beside the secret so the pair stays in sync)
    - OAuth app secret (the gloas-... value the user got at app
      registration time)

Each entry is keyed by the GitLab host so a single workstation can
talk to gitlab.com and a self-managed instance at the same time.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.config import TuochatConfig

logger = logging.getLogger("tuochat.security.credentials")

SERVICE_NAME = "tuochat"
SECRET_USERNAME_TEMPLATE = "{host}#secrets"


@dataclass
class StoredCredentials:
    """Bundle of credentials persisted for one GitLab host."""

    host: str = ""
    token_type: str = "pat"  # "pat" or "oauth"
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # epoch seconds; 0 = unknown / non-expiring
    oauth_app_id: str = ""
    oauth_app_secret: str = ""
    oauth_redirect: str = ""
    scopes: list[str] = field(default_factory=list)

    def is_oauth(self) -> bool:
        """Return True when this bundle represents an OAuth-issued token."""
        return self.token_type == "oauth"

    def access_token_expired(self, leeway: int = 60) -> bool:
        """Return True when the access token will expire within ``leeway`` seconds."""
        if not self.expires_at:
            return False
        return time.time() + leeway >= self.expires_at


def import_keyring():
    """Import keyring lazily; return None if it cannot be initialized."""
    try:
        import keyring  # noqa: PLC0415

        # Some backends raise on first use rather than at import time;
        # ping the backend to make sure it actually works.
        keyring.get_keyring()
        return keyring
    except Exception as exc:  # pragma: no cover - backend availability varies
        logger.warning("keyring is not usable: %s", exc)
        return None


def secret_username(host: str) -> str:
    """Return the username field used for keyring lookups for ``host``."""
    return SECRET_USERNAME_TEMPLATE.format(host=host or "default")


def serialize(creds: StoredCredentials) -> str:
    """Serialize credentials to a JSON blob suitable for the secret store."""
    return json.dumps(asdict(creds))


def deserialize(blob: str) -> StoredCredentials:
    """Parse a JSON blob produced by :func:`serialize`."""
    data = json.loads(blob)
    return StoredCredentials(
        host=str(data.get("host", "")),
        token_type=str(data.get("token_type", "pat")),
        access_token=str(data.get("access_token", "")),
        refresh_token=str(data.get("refresh_token", "")),
        expires_at=float(data.get("expires_at", 0.0) or 0.0),
        oauth_app_id=str(data.get("oauth_app_id", "")),
        oauth_app_secret=str(data.get("oauth_app_secret", "")),
        oauth_redirect=str(data.get("oauth_redirect", "")),
        scopes=[str(scope) for scope in data.get("scopes", []) or []],
    )


def keyring_available() -> bool:
    """Return True when an OS secret store can be reached."""
    return import_keyring() is not None


def save_to_keyring(creds: StoredCredentials) -> bool:
    """Persist ``creds`` to the OS secret store. Returns False on failure."""
    keyring = import_keyring()
    if keyring is None:
        return False
    try:
        keyring.set_password(SERVICE_NAME, secret_username(creds.host), serialize(creds))
        return True
    except Exception as exc:  # pragma: no cover - backend specific
        logger.warning("Failed to save credentials to keyring: %s", exc)
        return False


def load_from_keyring(host: str) -> StoredCredentials | None:
    """Read credentials for ``host`` from the OS secret store."""
    keyring = import_keyring()
    if keyring is None:
        return None
    try:
        blob = keyring.get_password(SERVICE_NAME, secret_username(host))
    except Exception as exc:  # pragma: no cover - backend specific
        logger.warning("Failed to read credentials from keyring: %s", exc)
        return None
    if not blob:
        return None
    try:
        return deserialize(blob)
    except Exception as exc:
        logger.warning("Stored credential blob is corrupt: %s", exc)
        return None


def delete_from_keyring(host: str) -> bool:
    """Remove credentials for ``host`` from the OS secret store."""
    keyring = import_keyring()
    if keyring is None:
        return False
    try:
        keyring.delete_password(SERVICE_NAME, secret_username(host))
        return True
    except Exception as exc:  # pragma: no cover - backend specific
        logger.info("Nothing to delete from keyring: %s", exc)
        return False


def load_credentials(cfg: TuochatConfig) -> StoredCredentials | None:
    """Resolve the active credentials for ``cfg``.

    Resolution order:
        1. Keyring entry for the configured host.
        2. Token already present on the config object (env var or
           config file fallback).
    """
    host = cfg.gitlab.host
    if host:
        from_keyring = load_from_keyring(host)
        if from_keyring is not None and from_keyring.access_token:
            return from_keyring
    if cfg.gitlab.token:
        return StoredCredentials(
            host=host,
            token_type=cfg.gitlab.token_type or "pat",
            access_token=cfg.gitlab.token,
        )
    return None


def apply_credentials(cfg: TuochatConfig, creds: StoredCredentials) -> None:
    """Copy resolved credentials onto the config object so existing call sites work."""
    cfg.gitlab.host = creds.host or cfg.gitlab.host
    cfg.gitlab.token = creds.access_token
    cfg.gitlab.token_type = creds.token_type or "pat"


def store_credentials(cfg: TuochatConfig, creds: StoredCredentials, *, prefer_keyring: bool) -> str:
    """Persist credentials and return a human-readable description of where they went.

    When ``prefer_keyring`` is True we try the OS secret store first and
    only fall back to the central config file if that fails. Otherwise
    the credentials are written straight to config (the existing
    behavior for users who explicitly opted out of the secret store).
    """
    from tuochat.config import save_config  # noqa: PLC0415 - avoid import cycle

    if prefer_keyring and save_to_keyring(creds):
        # Wipe any plaintext token from the config file so we don't
        # have two sources of truth that can drift apart.
        cfg.gitlab.token = ""
        cfg.gitlab.token_type = creds.token_type
        save_config(cfg)
        return f"OS secret store ({SERVICE_NAME}/{secret_username(creds.host)})"

    cfg.gitlab.token = creds.access_token
    cfg.gitlab.token_type = creds.token_type
    save_config(cfg)
    return str(cfg.config_file)


__all__ = [
    "SERVICE_NAME",
    "StoredCredentials",
    "apply_credentials",
    "delete_from_keyring",
    "import_keyring",
    "keyring_available",
    "load_credentials",
    "load_from_keyring",
    "save_to_keyring",
    "secret_username",
    "store_credentials",
]
