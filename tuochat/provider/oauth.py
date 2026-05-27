"""GitLab OAuth 2.0 (Authorization Code + PKCE) for tuochat.

GitLab supports the standard OAuth 2.0 flows documented at
https://docs.gitlab.com/ee/api/oauth2.html. We use the
authorization-code flow with a PKCE challenge and a loopback redirect
URI so that desktop installs of tuochat can authenticate without ever
exposing the client secret to the browser.

The flow:

    1. Generate a PKCE verifier + challenge and a CSRF state token.
    2. Spin up a one-shot HTTP server bound to 127.0.0.1 on the port
       requested by the configured redirect URI.
    3. Open the user's browser to the GitLab /oauth/authorize page.
    4. GitLab redirects back with ``code`` and ``state``; we validate
       state, then POST to /oauth/token to exchange the code for an
       access + refresh token pair.
    5. Persist the resulting :class:`StoredCredentials`.

We use only the standard library so this module imposes no extra
dependencies on the existing tuochat install.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError

from tuochat.config import default_gitlab_user_agent

if TYPE_CHECKING:
    from tuochat.security.credentials import StoredCredentials

logger = logging.getLogger("tuochat.provider.oauth")

DEFAULT_REDIRECT = "http://127.0.0.1:8765/callback"
DEFAULT_SCOPES = ("ai_features", "read_api", "read_user", "read_repository")
AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"
OAUTH_TOKEN_TYPE = "oauth"


class OAuthError(RuntimeError):
    """Raised when an OAuth exchange or refresh fails."""


@dataclass
class OAuthClient:
    """Static configuration for a single GitLab OAuth application."""

    host: str
    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_REDIRECT
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    user_agent: str = field(default_factory=default_gitlab_user_agent)

    def authorize_url(self, *, state: str, code_challenge: str) -> str:
        """Return the GitLab /oauth/authorize URL for this client."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": " ".join(self.scopes),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.host.rstrip('/')}{AUTHORIZE_PATH}?{urllib.parse.urlencode(params)}"

    def token_endpoint(self) -> str:
        """Return the GitLab /oauth/token URL for this client."""
        return f"{self.host.rstrip('/')}{TOKEN_PATH}"


def make_pkce_pair() -> tuple[str, str]:
    """Return a (verifier, challenge) PKCE pair using the S256 method."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def parse_redirect(redirect_uri: str) -> tuple[str, int, str]:
    """Return (host, port, path) for a loopback OAuth redirect URI."""
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 0
    path = parsed.path or "/"
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise OAuthError(
            f"Refusing to bind a non-loopback OAuth redirect host: {host!r}. "
            "Use 127.0.0.1 or localhost so the auth code never leaves your machine."
        )
    return host, port, path


def loopback_port_available(host: str, port: int) -> bool:
    """Return True when ``host:port`` can be bound right now."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


@dataclass
class CallbackResult:
    """Captured query parameters from the OAuth redirect."""

    code: str = ""
    state: str = ""
    error: str = ""
    error_description: str = ""


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot handler that records the OAuth ``code`` and ``state``."""

    captured: CallbackResult
    expected_path: str
    done_event: threading.Event

    def log_message(self, format: str, *args) -> None:  # noqa: A002 # pylint: disable=redefined-builtin
        """Silence default stderr access logs."""
        logger.debug("oauth callback: " + format, *args)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        """Capture query params and return a friendly success/failure page."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != self.expected_path:
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        self.captured.code = (params.get("code") or [""])[0]
        self.captured.state = (params.get("state") or [""])[0]
        self.captured.error = (params.get("error") or [""])[0]
        self.captured.error_description = (params.get("error_description") or [""])[0]

        if self.captured.error:
            body = (
                "<html><body><h1>tuochat: OAuth failed</h1>"
                f"<p><b>{self.captured.error}</b>: {self.captured.error_description}</p>"
                "<p>You can close this tab.</p></body></html>"
            )
            self.send_response(400)
        elif self.captured.code:
            body = (
                "<html><body><h1>tuochat: signed in</h1>"
                "<p>Authentication succeeded. You can close this tab and return to your terminal.</p>"
                "</body></html>"
            )
            self.send_response(200)
        else:
            body = "<html><body><h1>tuochat: missing code</h1></body></html>"
            self.send_response(400)

        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
        self.done_event.set()


def wait_for_callback(host: str, port: int, path: str, *, timeout: float) -> CallbackResult:
    """Run a single-request HTTP server and return the captured query params."""
    captured = CallbackResult()
    done = threading.Event()

    handler_class = type(
        "BoundCallbackHandler",
        (CallbackHandler,),
        {"captured": captured, "expected_path": path, "done_event": done},
    )
    server = http.server.HTTPServer((host, port), handler_class)
    thread = threading.Thread(target=server.serve_forever, name="tuochat-oauth-callback", daemon=True)
    thread.start()
    try:
        if not done.wait(timeout=timeout):
            raise OAuthError(
                f"Timed out after {int(timeout)}s waiting for the GitLab OAuth redirect to {host}:{port}{path}."
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return captured


def validate_https_request_target(url: str, *, allowed_hosts: set[str], label: str) -> str:
    """Validate that an outbound OAuth request targets the expected HTTPS host."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise OAuthError(f"{label} must use an https:// URL, got: {url!r}")
    if parsed.hostname not in allowed_hosts:
        raise OAuthError(f"{label} must target {sorted(allowed_hosts)!r}, got: {parsed.hostname!r}")
    return url


def post_token_request(client: OAuthClient, payload: dict[str, str]) -> dict:
    """POST to the GitLab token endpoint and return the parsed JSON body."""
    allowed_host = urllib.parse.urlparse(client.host).hostname
    if not allowed_host:
        raise OAuthError(f"GitLab host must include a hostname, got: {client.host!r}")
    token_url = validate_https_request_target(
        client.token_endpoint(),
        allowed_hosts={allowed_host},
        label="GitLab token endpoint",
    )
    body = urllib.parse.urlencode(payload).encode("ascii")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    if client.user_agent:
        headers["User-Agent"] = client.user_agent
    request = urllib.request.Request(
        token_url,
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise OAuthError(f"GitLab token endpoint returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise OAuthError(f"Could not reach GitLab token endpoint: {exc.reason}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OAuthError(f"GitLab token endpoint returned non-JSON: {raw[:200]!r}") from exc
    if "error" in data:
        raise OAuthError(f"GitLab token error: {data.get('error')} - {data.get('error_description', '')}")
    return data


def credentials_from_token_response(client: OAuthClient, data: dict) -> StoredCredentials:
    """Build a :class:`StoredCredentials` instance from a token response payload."""
    from tuochat.security.credentials import StoredCredentials  # noqa: PLC0415

    expires_in = float(data.get("expires_in", 0) or 0)
    return StoredCredentials(
        host=client.host,
        token_type=OAUTH_TOKEN_TYPE,
        access_token=str(data.get("access_token", "")),
        refresh_token=str(data.get("refresh_token", "")),
        expires_at=time.time() + expires_in if expires_in else 0.0,
        oauth_app_id=client.client_id,
        oauth_app_secret=client.client_secret,
        oauth_redirect=client.redirect_uri,
        scopes=list(client.scopes),
    )


def run_authorization_flow(
    client: OAuthClient,
    *,
    open_browser: bool = True,
    timeout: float = 300.0,
) -> StoredCredentials:
    """Drive the full Authorization Code + PKCE flow and return credentials."""
    host, port, path = parse_redirect(client.redirect_uri)
    if not loopback_port_available(host, port):
        raise OAuthError(
            f"Local port {host}:{port} is already in use. Close whatever is bound to it "
            "or set TUOCHAT_OAUTH_REDIRECT to a free loopback port."
        )

    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)
    url = client.authorize_url(state=state, code_challenge=challenge)

    print("Opening your browser to authorize tuochat with GitLab...")
    print(f"  {url}")
    print(f"Listening for the redirect on {host}:{port}{path} (Ctrl+C to abort).")
    if open_browser:
        try:
            webbrowser.open(url, new=2)
        except Exception as exc:  # pragma: no cover - browser availability varies
            logger.warning("Could not open browser automatically: %s", exc)

    captured = wait_for_callback(host, port, path, timeout=timeout)
    if captured.error:
        raise OAuthError(f"GitLab returned an OAuth error: {captured.error} - {captured.error_description}")
    if captured.state != state:
        raise OAuthError("OAuth state mismatch -- possible CSRF, aborting.")
    if not captured.code:
        raise OAuthError("GitLab did not return an authorization code.")

    payload = {
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "code": captured.code,
        "grant_type": "authorization_code",
        "redirect_uri": client.redirect_uri,
        "code_verifier": verifier,
    }
    data = post_token_request(client, payload)
    return credentials_from_token_response(client, data)


def refresh_access_token(client: OAuthClient, refresh_token: str) -> StoredCredentials:
    """Trade a refresh token for a fresh access token."""
    if not refresh_token:
        raise OAuthError("Cannot refresh: no refresh token on file.")
    payload = {
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "redirect_uri": client.redirect_uri,
    }
    data = post_token_request(client, payload)
    return credentials_from_token_response(client, data)


__all__ = [
    "DEFAULT_REDIRECT",
    "DEFAULT_SCOPES",
    "OAuthClient",
    "OAuthError",
    "credentials_from_token_response",
    "make_pkce_pair",
    "parse_redirect",
    "post_token_request",
    "refresh_access_token",
    "run_authorization_flow",
]
