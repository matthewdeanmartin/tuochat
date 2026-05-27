"""Keyring storage for the OpenRouter API key.

Reuses the same `keyring` backend as the GitLab credential store, but
under a dedicated keyring username so it is independent of any GitLab
host entries.  When keyring is unavailable, callers fall back to the
`OPENROUTER_API_KEY` environment variable or the central config file.
"""

from __future__ import annotations

import logging

from tuochat.security.credentials import import_keyring

logger = logging.getLogger("tuochat.security.openrouter_secret")

SERVICE_NAME = "tuochat"
KEYRING_USERNAME = "openrouter#api_key"


def save_api_key(api_key: str) -> bool:
    """Persist the OpenRouter API key in the OS secret store."""
    keyring = import_keyring()
    if keyring is None:
        return False
    try:
        keyring.set_password(SERVICE_NAME, KEYRING_USERNAME, api_key)
        return True
    except Exception as exc:  # pragma: no cover - backend specific
        logger.warning("Failed to save OpenRouter API key to keyring: %s", exc)
        return False


def load_api_key() -> str | None:
    """Read the OpenRouter API key from the OS secret store."""
    keyring = import_keyring()
    if keyring is None:
        return None
    try:
        value = keyring.get_password(SERVICE_NAME, KEYRING_USERNAME)
    except Exception as exc:  # pragma: no cover - backend specific
        logger.warning("Failed to read OpenRouter API key from keyring: %s", exc)
        return None
    return value or None


def delete_api_key() -> bool:
    """Remove any stored OpenRouter API key from the OS secret store."""
    keyring = import_keyring()
    if keyring is None:
        return False
    try:
        keyring.delete_password(SERVICE_NAME, KEYRING_USERNAME)
        return True
    except Exception as exc:  # pragma: no cover - backend specific
        logger.info("Nothing to delete from keyring: %s", exc)
        return False


__all__ = [
    "KEYRING_USERNAME",
    "SERVICE_NAME",
    "delete_api_key",
    "load_api_key",
    "save_api_key",
]
