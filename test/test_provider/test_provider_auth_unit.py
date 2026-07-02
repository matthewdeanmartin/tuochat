from __future__ import annotations

import io
import json
import socket
import threading
import time
import urllib.request
from email.message import Message

import pytest

from tuochat.cli.commands import auth_cmd
from tuochat.config import GitLabConfig, TuochatConfig
from tuochat.provider import oauth, proxy
from tuochat.security.credentials import StoredCredentials


class UrlopenResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.body = body.encode("utf-8")
        self.status = status

    def __enter__(self) -> UrlopenResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def make_cfg(tmp_path, host: str = "https://gitlab.example.com") -> TuochatConfig:
    return TuochatConfig(
        gitlab=GitLabConfig(host=host),
        config_dir=tmp_path,
        data_dir=tmp_path,
        log_dir=tmp_path,
    )


def reserve_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


def wait_for_http_server(port: int) -> None:
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                return
        except OSError:
            time.sleep(0.01)
    raise AssertionError(f"server on port {port} never became ready")


def test_oauth_client_builds_authorize_and_token_urls():
    client = oauth.OAuthClient(
        host="https://gitlab.example.com/",
        client_id="app-id",
        client_secret="app-secret",
        redirect_uri="http://127.0.0.1:8765/callback",
    )

    url = client.authorize_url(state="csrf-state", code_challenge="challenge")

    assert url.startswith("https://gitlab.example.com/oauth/authorize?")
    assert "client_id=app-id" in url
    assert "state=csrf-state" in url
    assert "code_challenge=challenge" in url
    assert client.token_endpoint() == "https://gitlab.example.com/oauth/token"


def test_make_pkce_pair_returns_urlsafe_verifier_and_challenge():
    verifier, challenge = oauth.make_pkce_pair()

    assert len(verifier) >= 40
    assert len(challenge) >= 40
    assert "=" not in verifier
    assert "=" not in challenge
    assert verifier != challenge


def test_parse_redirect_rejects_non_loopback_host():
    with pytest.raises(oauth.OAuthError, match="non-loopback"):
        oauth.parse_redirect("http://example.com:8765/callback")


def test_wait_for_callback_captures_code_and_state():
    port = reserve_loopback_port()
    holder: dict[str, oauth.CallbackResult] = {}

    def run_server() -> None:
        holder["result"] = oauth.wait_for_callback("127.0.0.1", port, "/callback", timeout=2)

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    wait_for_http_server(port)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=state-1", timeout=2) as response:
        body = response.read().decode("utf-8")

    thread.join(timeout=2)
    result = holder["result"]
    assert response.status == 200
    assert "signed in" in body
    assert result.code == "abc123"
    assert result.state == "state-1"


def test_post_token_request_parses_json(monkeypatch):
    client = oauth.OAuthClient(host="https://gitlab.example.com", client_id="cid", client_secret="secret")
    seen: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> UrlopenResponse:
        seen["url"] = request.full_url
        seen["body"] = request.data
        seen["timeout"] = timeout
        seen["user_agent"] = request.get_header("User-agent")
        return UrlopenResponse(json.dumps({"access_token": "tok", "refresh_token": "ref"}))

    monkeypatch.setattr(oauth.urllib.request, "urlopen", fake_urlopen)

    data = oauth.post_token_request(client, {"grant_type": "refresh_token", "refresh_token": "ref"})

    assert data["access_token"] == "tok"
    assert seen["url"] == "https://gitlab.example.com/oauth/token"
    assert b"grant_type=refresh_token" in seen["body"]
    assert seen["timeout"] == 30
    assert seen["user_agent"] == client.user_agent


def test_post_token_request_rewraps_http_errors(monkeypatch):
    client = oauth.OAuthClient(host="https://gitlab.example.com", client_id="cid", client_secret="secret")

    def fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ARG001
        raise oauth.HTTPError(
            url=request.full_url,
            code=400,
            msg="bad request",
            hdrs=Message(),
            fp=io.BytesIO(b'{"error":"invalid_grant"}'),
        )

    monkeypatch.setattr(oauth.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(oauth.OAuthError, match="HTTP 400"):
        oauth.post_token_request(client, {"grant_type": "refresh_token"})


def test_post_token_request_rejects_non_json(monkeypatch):
    client = oauth.OAuthClient(host="https://gitlab.example.com", client_id="cid", client_secret="secret")
    monkeypatch.setattr(
        oauth.urllib.request, "urlopen", lambda request, timeout: UrlopenResponse("not-json")
    )  # noqa: ARG005

    with pytest.raises(oauth.OAuthError, match="non-JSON"):
        oauth.post_token_request(client, {"grant_type": "authorization_code"})


def test_credentials_from_token_response_uses_expires_in(monkeypatch):
    client = oauth.OAuthClient(host="https://gitlab.example.com", client_id="cid", client_secret="secret")
    monkeypatch.setattr(oauth.time, "time", lambda: 1_000.0)

    creds = oauth.credentials_from_token_response(
        client,
        {"access_token": "acc", "refresh_token": "ref", "expires_in": 60},
    )

    assert creds.access_token == "acc"
    assert creds.refresh_token == "ref"
    assert creds.expires_at == pytest.approx(1_060.0)
    assert creds.oauth_app_id == "cid"


def test_run_authorization_flow_exchanges_code_for_credentials(monkeypatch, capsys):
    client = oauth.OAuthClient(host="https://gitlab.example.com", client_id="cid", client_secret="secret")
    browser_urls: list[str] = []
    seen_payload: dict[str, str] = {}

    monkeypatch.setattr(oauth, "loopback_port_available", lambda host, port: True)
    monkeypatch.setattr(oauth, "make_pkce_pair", lambda: ("verifier-1", "challenge-1"))
    monkeypatch.setattr(oauth.secrets, "token_urlsafe", lambda n: "state-xyz")
    monkeypatch.setattr(
        oauth,
        "wait_for_callback",
        lambda host, port, path, timeout: oauth.CallbackResult(code="auth-code", state="state-xyz"),
    )
    monkeypatch.setattr(oauth.webbrowser, "open", lambda url, new=2: browser_urls.append(url))

    def fake_post_token_request(client_arg: oauth.OAuthClient, payload: dict[str, str]) -> dict[str, object]:
        assert client_arg is client
        seen_payload.update(payload)
        return {"access_token": "acc", "refresh_token": "ref", "expires_in": 30}

    monkeypatch.setattr(oauth, "post_token_request", fake_post_token_request)
    monkeypatch.setattr(oauth.time, "time", lambda: 500.0)

    creds = oauth.run_authorization_flow(client)

    out = capsys.readouterr().out
    assert "Opening your browser" in out
    assert browser_urls and "challenge-1" in browser_urls[0]
    assert seen_payload["code"] == "auth-code"
    assert seen_payload["code_verifier"] == "verifier-1"
    assert creds.access_token == "acc"
    assert creds.expires_at == pytest.approx(530.0)


def test_refresh_access_token_requires_refresh_token():
    client = oauth.OAuthClient(host="https://gitlab.example.com", client_id="cid", client_secret="secret")

    with pytest.raises(oauth.OAuthError, match="no refresh token"):
        oauth.refresh_access_token(client, "")


def test_refresh_access_token_uses_token_endpoint(monkeypatch):
    client = oauth.OAuthClient(host="https://gitlab.example.com", client_id="cid", client_secret="secret")
    monkeypatch.setattr(
        oauth,
        "post_token_request",
        lambda client_arg, payload: {"access_token": "fresh", "refresh_token": payload["refresh_token"]},
    )

    creds = oauth.refresh_access_token(client, "refresh-1")

    assert creds.access_token == "fresh"
    assert creds.refresh_token == "refresh-1"


def test_proxy_env_vars_snapshot_reads_case_insensitive_env(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy-secure.local:8443")
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.setenv("ALL_PROXY", "socks5://ignored:1080")

    env_vars = proxy.ProxyEnvVars.snapshot()

    assert env_vars.any_set() is True
    assert env_vars.effective_proxy() == "http://proxy-secure.local:8443"
    assert env_vars.as_dict()["NO_PROXY"] == "localhost"


def test_probe_result_summarizes_and_parses_proxy_url():
    result = proxy.ProbeResult(
        strategy=proxy.ProxyStrategy.ENV,
        proxy_url="http://proxy.local:8888",
        env_vars=proxy.ProxyEnvVars(None, None, None, None),
    )

    assert result.summary() == "env proxy (http://proxy.local:8888)"
    assert result.proxy_host_port() == ("proxy.local", 8888)


def test_proxy_probe_wpad_url_candidates_add_domain(monkeypatch):
    probe_instance = proxy.ProxyProbe("https://gitlab.example.com")
    monkeypatch.setattr(proxy.socket, "getfqdn", lambda: "workstation.corp.example.com")

    candidates = probe_instance.wpad_url_candidates()

    assert candidates == ["http://wpad/wpad.dat", "http://wpad.corp.example.com/wpad.dat"]


def test_proxy_probe_prefers_env_when_env_connects(monkeypatch):
    env_vars = proxy.ProxyEnvVars("http://proxy.local:8080", None, None, None)
    probe_instance = proxy.ProxyProbe("https://gitlab.example.com")

    monkeypatch.setattr(proxy.ProxyEnvVars, "snapshot", classmethod(lambda cls: env_vars))
    monkeypatch.setattr(
        probe_instance,
        "try_connect",
        lambda opener, label: label == "env-proxy",
    )

    result = probe_instance.probe()

    assert result.strategy == proxy.ProxyStrategy.ENV
    assert result.proxy_url == "http://proxy.local:8080"
    assert any("env proxy" in note.lower() for note in result.notes)


def test_proxy_probe_falls_back_to_direct_then_wpad(monkeypatch):
    env_vars = proxy.ProxyEnvVars("http://bad-proxy.local:8080", None, None, None)
    probe_instance = proxy.ProxyProbe("https://gitlab.example.com")

    monkeypatch.setattr(proxy.ProxyEnvVars, "snapshot", classmethod(lambda cls: env_vars))
    monkeypatch.setattr(
        probe_instance,
        "try_connect",
        lambda opener, label: label == "wpad",
    )
    monkeypatch.setattr(
        probe_instance, "fetch_wpad", lambda: 'function FindProxyForURL(){ return "PROXY proxy.corp:8080; DIRECT"; }'
    )

    result = probe_instance.probe()

    assert result.strategy == proxy.ProxyStrategy.WPAD
    assert result.proxy_url == "http://proxy.corp:8080"
    assert any("direct connection failed" in note.lower() for note in result.notes)


def test_get_session_proxy_caches_until_cleared(monkeypatch):
    proxy.clear_session_proxy()
    calls: list[str] = []

    def fake_resolve(self) -> proxy.ProbeResult:
        calls.append(self.gitlab_host)
        return proxy.ProbeResult(
            strategy=proxy.ProxyStrategy.DIRECT,
            proxy_url=None,
            env_vars=proxy.ProxyEnvVars(None, None, None, None),
        )

    monkeypatch.setattr(proxy.ProxyProbe, "resolve", fake_resolve)

    first = proxy.get_session_proxy("https://gitlab.example.com")
    second = proxy.get_session_proxy("https://gitlab.other.example")

    assert first is second
    assert calls == ["https://gitlab.example.com"]

    proxy.clear_session_proxy()
    proxy.get_session_proxy("https://gitlab.other.example")
    assert calls == ["https://gitlab.example.com", "https://gitlab.other.example"]


def test_env_oauth_defaults_reads_environment(monkeypatch):
    monkeypatch.setenv("TUOCHAT_OAUTH_APP_ID", "app-id")
    monkeypatch.setenv("TUOCHAT_OAUTH_SECRET", "app-secret")
    monkeypatch.setenv("TUOCHAT_OAUTH_REDIRECT", "http://127.0.0.1:9999/callback")

    defaults = auth_cmd.env_oauth_defaults()

    assert defaults == {
        "client_id": "app-id",
        "client_secret": "app-secret",
        "redirect_uri": "http://127.0.0.1:9999/callback",
    }


def test_resolve_oauth_client_uses_env_and_keyring(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    monkeypatch.setenv("TUOCHAT_OAUTH_APP_ID", "env-id")
    monkeypatch.delenv("TUOCHAT_OAUTH_SECRET", raising=False)
    monkeypatch.setattr(
        auth_cmd,
        "load_from_keyring",
        lambda host: StoredCredentials(
            host=host,
            oauth_app_id="stored-id",
            oauth_app_secret="stored-secret",
            oauth_redirect="http://127.0.0.1:8765/callback",
        ),
    )

    client = auth_cmd.resolve_oauth_client(cfg, prompt_for_missing=False)

    assert client.client_id == "env-id"
    assert client.client_secret == "stored-secret"
    assert client.redirect_uri == oauth.DEFAULT_REDIRECT
    assert client.user_agent == cfg.gitlab.user_agent


def test_resolve_oauth_client_prompts_for_missing_fields(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    monkeypatch.delenv("TUOCHAT_OAUTH_APP_ID", raising=False)
    monkeypatch.delenv("TUOCHAT_OAUTH_SECRET", raising=False)
    monkeypatch.delenv("TUOCHAT_OAUTH_REDIRECT", raising=False)
    monkeypatch.setattr(auth_cmd, "load_from_keyring", lambda host: None)
    monkeypatch.setattr(
        auth_cmd, "prompt_nonempty", lambda prompt, secret=False: "prompted-secret" if secret else "prompted-id"
    )
    monkeypatch.setattr(auth_cmd, "prompt_text", lambda prompt, default="": "http://127.0.0.1:9000/callback")

    client = auth_cmd.resolve_oauth_client(cfg, prompt_for_missing=True)

    assert client.client_id == "prompted-id"
    assert client.client_secret == "prompted-secret"
    assert client.redirect_uri == "http://127.0.0.1:9000/callback"


def test_offer_storage_choice_returns_false_without_keyring(monkeypatch, capsys):
    monkeypatch.setattr(auth_cmd, "keyring_available", lambda: False)

    prefer_keyring = auth_cmd.offer_storage_choice()

    out = capsys.readouterr().out
    assert prefer_keyring is False
    assert "no OS secret store detected" in out


def test_collect_pat_returns_pat_credentials(monkeypatch, tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(auth_cmd, "prompt_nonempty", lambda prompt, secret=False: "glpat-token")

    creds = auth_cmd.collect_pat(cfg)

    out = capsys.readouterr().out
    assert "personal_access_tokens" in out
    assert creds.token_type == "pat"
    assert creds.access_token == "glpat-token"


def test_ensure_host_prompts_and_saves(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path, host="")
    saved: list[TuochatConfig] = []
    monkeypatch.setattr(auth_cmd, "prompt_text", lambda prompt, default="": "gitlab.example.com")
    monkeypatch.setattr(auth_cmd, "save_config", lambda cfg_arg: saved.append(cfg_arg))

    auth_cmd.ensure_host(cfg)

    assert cfg.gitlab.host == "https://gitlab.example.com"
    assert saved == [cfg]


def test_interactive_login_pat_branch_stores_credentials(monkeypatch, tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    stored: list[tuple[StoredCredentials, bool]] = []
    monkeypatch.setattr(auth_cmd, "prompt_input", lambda prompt: "1")
    monkeypatch.setattr(
        auth_cmd,
        "collect_pat",
        lambda cfg_arg: StoredCredentials(host=cfg_arg.gitlab.host, token_type="pat", access_token="tok"),
    )
    monkeypatch.setattr(auth_cmd, "offer_storage_choice", lambda default_keyring=True: False)
    monkeypatch.setattr(
        auth_cmd,
        "store_credentials",
        lambda cfg_arg, creds, prefer_keyring: stored.append((creds, prefer_keyring)) or str(cfg_arg.config_file),
    )

    creds = auth_cmd.interactive_login(cfg)

    out = capsys.readouterr().out
    assert creds.access_token == "tok"
    assert stored == [(creds, False)]
    assert "Credentials saved to:" in out


def test_run_login_returns_error_when_oauth_fails(monkeypatch, tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(auth_cmd, "interactive_login", lambda cfg_arg: (_ for _ in ()).throw(oauth.OAuthError("boom")))

    result = auth_cmd.run_login(cfg)

    out = capsys.readouterr().out
    assert result == 1
    assert "OAuth failed: boom" in out


def test_run_status_reports_oauth_details(monkeypatch, tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(auth_cmd, "keyring_available", lambda: True)
    monkeypatch.setattr(
        auth_cmd,
        "load_credentials",
        lambda cfg_arg: StoredCredentials(
            host=cfg_arg.gitlab.host,
            token_type="oauth",
            access_token="acc",
            refresh_token="ref",
            expires_at=200.0,
            scopes=["ai_features", "read_api"],
        ),
    )
    monkeypatch.setattr(auth_cmd, "load_from_keyring", lambda host: StoredCredentials(host=host, access_token="acc"))
    monkeypatch.setattr("time.time", lambda: 150.0)

    result = auth_cmd.run_status(cfg)

    out = capsys.readouterr().out
    assert result == 0
    assert "Token type: oauth" in out
    assert "Access token expires in: 50s" in out
    assert "Storage: keyring" in out


def test_run_logout_clears_keyring_and_config(monkeypatch, tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    cfg.gitlab.token = "old-token"
    monkeypatch.setattr(auth_cmd, "delete_from_keyring", lambda host: True)

    result = auth_cmd.run_logout(cfg)

    out = capsys.readouterr().out
    assert result == 0
    assert cfg.gitlab.token == ""
    assert "Removed from keyring: True" in out
    assert "Cleared config token: True" in out


def test_run_refresh_falls_back_to_config_file(monkeypatch, tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(
        auth_cmd,
        "load_credentials",
        lambda cfg_arg: StoredCredentials(
            host=cfg_arg.gitlab.host,
            token_type="oauth",
            access_token="old-access",
            refresh_token="refresh-token",
            oauth_app_id="cid",
            oauth_app_secret="secret",
        ),
    )
    monkeypatch.setattr(
        auth_cmd,
        "resolve_oauth_client",
        lambda cfg_arg, prompt_for_missing=False: oauth.OAuthClient(
            host=cfg_arg.gitlab.host, client_id="cid", client_secret="secret"
        ),
    )
    monkeypatch.setattr(
        auth_cmd,
        "refresh_access_token",
        lambda client, refresh_token: StoredCredentials(
            host=client.host,
            token_type="oauth",
            access_token="fresh-access",
            refresh_token=refresh_token,
        ),
    )
    monkeypatch.setattr(auth_cmd, "save_to_keyring", lambda creds: False)

    result = auth_cmd.run_refresh(cfg)

    out = capsys.readouterr().out
    assert result == 0
    assert cfg.gitlab.token == "fresh-access"
    assert cfg.gitlab.token_type == "oauth"
    assert "Refreshed access token saved to:" in out


def test_run_refresh_requires_oauth_refresh_token(monkeypatch, tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(auth_cmd, "load_credentials", lambda cfg_arg: None)

    result = auth_cmd.run_refresh(cfg)

    out = capsys.readouterr().out
    assert result == 1
    assert "No OAuth refresh token on file" in out
