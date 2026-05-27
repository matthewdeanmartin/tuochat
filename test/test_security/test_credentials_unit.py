from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from tuochat.security.credentials import (
    StoredCredentials,
    apply_credentials,
    delete_from_keyring,
    deserialize,
    keyring_available,
    load_credentials,
    load_from_keyring,
    save_to_keyring,
    secret_username,
    serialize,
    store_credentials,
)


def test_stored_credentials_is_oauth():
    creds = StoredCredentials(token_type="oauth")
    assert creds.is_oauth() is True
    creds.token_type = "pat"
    assert creds.is_oauth() is False


def test_access_token_expired():
    # Not expiring
    creds = StoredCredentials(expires_at=0.0)
    assert creds.access_token_expired() is False

    # Expired
    creds.expires_at = time.time() - 10
    assert creds.access_token_expired() is True

    # Not yet expired
    creds.expires_at = time.time() + 100
    assert creds.access_token_expired() is False


def test_serialize_deserialize():
    creds = StoredCredentials(
        host="gitlab.com", access_token="abc", refresh_token="def", expires_at=123.456, scopes=["api", "read_user"]
    )
    blob = serialize(creds)
    decoded = deserialize(blob)
    assert decoded.host == creds.host
    assert decoded.access_token == creds.access_token
    assert decoded.refresh_token == creds.refresh_token
    assert decoded.expires_at == pytest.approx(creds.expires_at)
    assert decoded.scopes == creds.scopes


def test_secret_username():
    assert "gitlab.com" in secret_username("gitlab.com")
    assert "default" in secret_username("")


@patch("tuochat.security.credentials.import_keyring")
def test_keyring_available(mock_import):
    mock_import.return_value = MagicMock()
    assert keyring_available() is True
    mock_import.return_value = None
    assert keyring_available() is False


@patch("tuochat.security.credentials.import_keyring")
def test_save_to_keyring(mock_import):
    mock_keyring = MagicMock()
    mock_import.return_value = mock_keyring
    creds = StoredCredentials(host="example.com", access_token="tok")

    assert save_to_keyring(creds) is True
    mock_keyring.set_password.assert_called_once()

    # Failure case
    mock_keyring.set_password.side_effect = Exception("boom")
    assert save_to_keyring(creds) is False


@patch("tuochat.security.credentials.import_keyring")
def test_load_from_keyring(mock_import):
    mock_keyring = MagicMock()
    mock_import.return_value = mock_keyring
    creds = StoredCredentials(host="example.com", access_token="tok")
    mock_keyring.get_password.return_value = serialize(creds)

    loaded = load_from_keyring("example.com")
    assert loaded is not None
    assert loaded.access_token == "tok"

    # Missing
    mock_keyring.get_password.return_value = None
    assert load_from_keyring("other.com") is None

    # Corrupt
    mock_keyring.get_password.return_value = "not json"
    assert load_from_keyring("example.com") is None


@patch("tuochat.security.credentials.import_keyring")
def test_delete_from_keyring(mock_import):
    mock_keyring = MagicMock()
    mock_import.return_value = mock_keyring

    assert delete_from_keyring("example.com") is True
    mock_keyring.delete_password.assert_called_once()

    # Failure (ignore)
    mock_keyring.delete_password.side_effect = Exception("not found")
    assert delete_from_keyring("example.com") is False


@patch("tuochat.security.credentials.load_from_keyring")
def test_load_credentials(mock_load_keyring):
    mock_cfg = MagicMock()
    mock_cfg.gitlab.host = "gitlab.com"
    mock_cfg.gitlab.token = "env-token"

    # Found in keyring
    keyring_creds = StoredCredentials(access_token="keyring-token")
    mock_load_keyring.return_value = keyring_creds

    result = load_credentials(mock_cfg)
    assert result.access_token == "keyring-token"

    # Not in keyring, fallback to config
    mock_load_keyring.return_value = None
    result = load_credentials(mock_cfg)
    assert result.access_token == "env-token"

    # Nowhere
    mock_cfg.gitlab.token = ""
    result = load_credentials(mock_cfg)
    assert result is None


def test_apply_credentials():
    mock_cfg = MagicMock()
    creds = StoredCredentials(host="host", access_token="tok", token_type="oauth")
    apply_credentials(mock_cfg, creds)
    assert mock_cfg.gitlab.host == "host"
    assert mock_cfg.gitlab.token == "tok"
    assert mock_cfg.gitlab.token_type == "oauth"


@patch("tuochat.security.credentials.save_to_keyring")
@patch("tuochat.config.save_config")
def test_store_credentials(mock_save_config, mock_save_keyring):
    mock_cfg = MagicMock()
    mock_cfg.config_file = "config.toml"
    creds = StoredCredentials(host="host", access_token="tok")

    # Prefer keyring, success
    mock_save_keyring.return_value = True
    msg = store_credentials(mock_cfg, creds, prefer_keyring=True)
    assert "secret store" in msg
    assert mock_cfg.gitlab.token == ""  # wiped from config
    mock_save_config.assert_called_once_with(mock_cfg)

    # Prefer keyring, failure, fallback to config
    mock_save_keyring.return_value = False
    mock_save_config.reset_mock()
    msg = store_credentials(mock_cfg, creds, prefer_keyring=True)
    assert "config.toml" in msg
    assert mock_cfg.gitlab.token == "tok"
    mock_save_config.assert_called_once_with(mock_cfg)
