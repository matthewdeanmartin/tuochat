"""Live integration test for OAuth + credential storage.

This exercises the GitLab-touching surfaces:

    - tuochat.security.credentials  (keyring round-trip + fallback)
    - tuochat.provider.oauth        (PKCE, authorize URL, callback server,
                                     token endpoint reachability)
    - tuochat.gitlab_client          (PAT auth against the live API)
    - tuochat.cli.commands.auth_cmd  (resolve_oauth_client wiring)

The test uses the live PAT in .env (TUOCHAT_GITLAB_TOKEN) so the GitLab
metadata client gets a real round-trip. The OAuth half is exercised
without actually completing the browser flow -- we drive the loopback
callback ourselves with a simulated GitLab redirect, then assert that
the token endpoint is reachable (a real exchange would need a fresh
GitLab-issued auth code, which we cannot fake).

Run:

    uv run python tests_integration/test_oauth_live.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env so the live PAT and OAuth client id are available.
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for raw_line in env_path.read_text().splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

HOST = os.environ["TUOCHAT_GITLAB_HOST"]
TOKEN = os.environ["TUOCHAT_GITLAB_TOKEN"]
APP_ID = os.environ.get("TUOCHAT_OAUTH_APP_ID", "")
APP_SECRET = os.environ.get("TUOCHAT_OAUTH_SECRET", "")
REDIRECT = os.environ.get("TUOCHAT_OAUTH_REDIRECT", "http://127.0.0.1:8765/callback")


def banner(label: str) -> None:
    """Print a section header so the script output stays scannable."""
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)


def test_credentials_round_trip_with_keyring() -> None:
    """Save and reload a PAT through the platform secret store."""
    from tuochat.security.credentials import (
        StoredCredentials,
        delete_from_keyring,
        keyring_available,
        load_from_keyring,
        save_to_keyring,
    )

    if not keyring_available():
        print("keyring backend not available on this host -- skipping")
        return

    test_host = "https://keyring-test.tuochat.invalid"
    sample = StoredCredentials(
        host=test_host,
        token_type="pat",
        access_token="glpat-test-do-not-use",
        oauth_app_id="abc123",
        oauth_app_secret="gloas-test",
        oauth_redirect=REDIRECT,
        scopes=["ai_features", "read_api"],
    )

    assert save_to_keyring(sample), "save_to_keyring should succeed when backend is available"
    try:
        loaded = load_from_keyring(test_host)
        assert loaded is not None, "round-trip read returned None"
        assert loaded.access_token == sample.access_token
        assert loaded.token_type == "pat"
        assert loaded.oauth_app_id == "abc123"
        assert loaded.scopes == ["ai_features", "read_api"]
        print(f"keyring round-trip OK ({loaded.token_type}, {len(loaded.access_token)} chars)")
    finally:
        delete_from_keyring(test_host)


def test_load_credentials_falls_back_to_config_token() -> None:
    """When the keyring has nothing, load_credentials should still see the env-supplied PAT."""
    from tuochat.config import load_config
    from tuochat.security.credentials import load_credentials

    cfg = load_config()
    creds = load_credentials(cfg)
    assert creds is not None and creds.access_token, "expected PAT from .env to be visible to load_credentials"
    print(f"load_credentials saw token_type={creds.token_type}, host={creds.host}")


def test_pat_against_live_gitlab() -> None:
    """Use the existing PAT to hit the real API and confirm wiring."""
    from tuochat.gitlab_client import GitLabMetaClient

    client = GitLabMetaClient(host=HOST, token=TOKEN, token_type="pat")
    user = client.gl.user  # python-gitlab lazy-loads on first attr access
    if user is None:
        client.gl.auth()
        user = client.gl.user
    assert user is not None, "python-gitlab returned no user for the PAT"
    print(f"authenticated to {HOST} as @{user.username}")


def test_pkce_pair_round_trips() -> None:
    """The PKCE pair must satisfy the S256 derivation rule."""
    import base64
    import hashlib

    from tuochat.provider.oauth import make_pkce_pair

    verifier, challenge = make_pkce_pair()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge == expected, "PKCE challenge does not match S256(verifier)"
    print(f"PKCE OK (verifier={len(verifier)} chars, challenge={len(challenge)} chars)")


def test_oauth_client_authorize_url_shape() -> None:
    """The authorize URL must point at the host and contain the required params."""
    from tuochat.provider.oauth import OAuthClient, make_pkce_pair

    if not APP_ID:
        print("TUOCHAT_OAUTH_APP_ID not set -- skipping authorize URL test")
        return
    client = OAuthClient(host=HOST, client_id=APP_ID, client_secret=APP_SECRET, redirect_uri=REDIRECT)
    _verifier, challenge = make_pkce_pair()
    url = client.authorize_url(state="test-state", code_challenge=challenge)

    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    assert parsed.netloc == urllib.parse.urlparse(HOST).netloc
    assert parsed.path == "/oauth/authorize"
    assert qs["client_id"] == [APP_ID]
    assert qs["redirect_uri"] == [REDIRECT]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["state"] == ["test-state"]
    assert "ai_features" in qs["scope"][0]
    print(f"authorize URL OK ({url[:80]}...)")


def test_callback_server_captures_simulated_redirect() -> None:
    """Drive the loopback callback server with a fake GitLab redirect."""
    from tuochat.provider.oauth import parse_redirect, wait_for_callback

    host, port, path = parse_redirect(REDIRECT)
    fake_code = "fake-auth-code-123"
    fake_state = "fake-state-xyz"
    callback_url = f"http://{host}:{port}{path}?code={fake_code}&state={fake_state}"

    result_box: dict = {}

    def hit_callback() -> None:
        # Give the server a moment to bind before we knock on the door.
        time.sleep(0.4)
        try:
            with urllib.request.urlopen(callback_url, timeout=5) as resp:  # noqa: S310 - loopback only
                result_box["status"] = resp.status
        except urllib.error.HTTPError as exc:
            result_box["status"] = exc.code
        except Exception as exc:
            result_box["error"] = str(exc)

    knocker = threading.Thread(target=hit_callback, name="oauth-callback-knocker", daemon=True)
    knocker.start()

    captured = wait_for_callback(host, port, path, timeout=10)
    knocker.join(timeout=5)

    assert "error" not in result_box, f"loopback request failed: {result_box.get('error')}"
    assert captured.code == fake_code
    assert captured.state == fake_state
    assert not captured.error
    print(f"loopback callback OK (code={captured.code[:8]}..., HTTP {result_box.get('status')})")


def test_token_endpoint_rejects_fake_code() -> None:
    """Confirm the token endpoint is reachable -- fake code should fail with an OAuth error, not a network error."""
    from tuochat.provider.oauth import OAuthClient, OAuthError, post_token_request

    if not APP_ID or not APP_SECRET:
        print("TUOCHAT_OAUTH_APP_ID / SECRET not set -- skipping token endpoint test")
        return
    client = OAuthClient(host=HOST, client_id=APP_ID, client_secret=APP_SECRET, redirect_uri=REDIRECT)
    payload = {
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "code": "definitely-not-a-real-code",
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT,
        "code_verifier": "x" * 64,
    }
    try:
        post_token_request(client, payload)
    except OAuthError as exc:
        msg = str(exc)
        assert "invalid_grant" in msg or "HTTP 400" in msg or "HTTP 401" in msg, f"unexpected token error shape: {msg}"
        print(f"token endpoint reachable, rejected fake code as expected: {msg[:120]}")
        return
    raise AssertionError("token endpoint accepted a fake authorization code -- impossible")


def test_resolve_oauth_client_uses_env_defaults() -> None:
    """The CLI helper should pick up env vars without prompting."""
    from tuochat.cli.commands.auth_cmd import resolve_oauth_client
    from tuochat.config import load_config

    if not APP_ID or not APP_SECRET:
        print("TUOCHAT_OAUTH_APP_ID / SECRET not set -- skipping resolver test")
        return
    cfg = load_config()
    client = resolve_oauth_client(cfg, prompt_for_missing=False)
    assert client.client_id == APP_ID
    assert client.client_secret == APP_SECRET
    assert client.redirect_uri == REDIRECT
    assert client.host == cfg.gitlab.host
    print(f"resolve_oauth_client OK (host={client.host}, redirect={client.redirect_uri})")


def main() -> int:
    """Run all checks. Bail out on the first failure with a clear marker."""
    tests = [
        ("credentials round-trip via keyring", test_credentials_round_trip_with_keyring),
        ("load_credentials sees env PAT", test_load_credentials_falls_back_to_config_token),
        ("PAT against live GitLab", test_pat_against_live_gitlab),
        ("PKCE S256 pair", test_pkce_pair_round_trips),
        ("OAuth authorize URL shape", test_oauth_client_authorize_url_shape),
        ("loopback callback server", test_callback_server_captures_simulated_redirect),
        ("token endpoint reachable", test_token_endpoint_rejects_fake_code),
        ("resolve_oauth_client env defaults", test_resolve_oauth_client_uses_env_defaults),
    ]
    failures = 0
    for label, fn in tests:
        banner(label)
        try:
            fn()
            print(f"PASS: {label}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {label}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"ERROR: {label}: {type(exc).__name__}: {exc}")
    banner("summary")
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
