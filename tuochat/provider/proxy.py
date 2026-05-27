"""Proxy auto-detection and configuration for GitLab connections.

Corporate networks are the #1 source of Duo connectivity failures.
This module probes the best proxy strategy once per session:

  1. Environment variables  (HTTP_PROXY / HTTPS_PROXY / NO_PROXY)
  2. No proxy               (direct connection)
  3. WPAD / PAC auto-discovery  (http://wpad/wpad.dat  or  http://wpad.<domain>/wpad.dat)

The winning strategy is cached for the remainder of the process so the
probe only runs once, at the first real GitLab connection.

Usage::

    probe = ProxyProbe(gitlab_host)
    result = probe.resolve()          # blocks briefly; cached after first call
    opener = result.build_opener()    # urllib opener pre-configured for the strategy
    # pass opener into DuoProvider(opener=opener)
"""

from __future__ import annotations

import logging
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("tuochat.provider.proxy")

PROBE_TIMEOUT = 8  # seconds per attempt
WPAD_TIMEOUT = 4  # shorter — WPAD may not exist at all


class ProxyStrategy(str, Enum):
    ENV = "env"  # use HTTP_PROXY / HTTPS_PROXY env vars
    DIRECT = "direct"  # bypass proxy entirely
    WPAD = "wpad"  # use proxy discovered via WPAD/PAC


@dataclass
class ProxyEnvVars:
    """Snapshot of proxy-related environment variables."""

    http_proxy: str | None
    https_proxy: str | None
    no_proxy: str | None
    all_proxy: str | None

    @classmethod
    def snapshot(cls) -> ProxyEnvVars:
        """Read current environment."""
        return cls(
            http_proxy=os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"),
            https_proxy=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
            no_proxy=os.environ.get("NO_PROXY") or os.environ.get("no_proxy"),
            all_proxy=os.environ.get("ALL_PROXY") or os.environ.get("all_proxy"),
        )

    def any_set(self) -> bool:
        return any(v is not None for v in (self.http_proxy, self.https_proxy, self.all_proxy))

    def effective_proxy(self) -> str | None:
        """Best proxy URL for HTTPS traffic."""
        return self.https_proxy or self.http_proxy or self.all_proxy

    def as_dict(self) -> dict[str, str | None]:
        return {
            "HTTP_PROXY": self.http_proxy,
            "HTTPS_PROXY": self.https_proxy,
            "NO_PROXY": self.no_proxy,
            "ALL_PROXY": self.all_proxy,
        }


@dataclass
class ProbeResult:
    """Outcome of a proxy probe."""

    strategy: ProxyStrategy
    proxy_url: str | None  # None for DIRECT
    env_vars: ProxyEnvVars
    notes: list[str] = field(default_factory=list)

    def build_opener(self) -> urllib.request.OpenerDirector:
        """Build a urllib opener pre-configured for this strategy."""
        if self.strategy == ProxyStrategy.DIRECT:
            # Explicitly bypass any system/env proxies
            handler = urllib.request.ProxyHandler({})
            return urllib.request.build_opener(handler)

        if self.strategy in (ProxyStrategy.ENV, ProxyStrategy.WPAD) and self.proxy_url:
            handler = urllib.request.ProxyHandler({"http": self.proxy_url, "https": self.proxy_url})
            return urllib.request.build_opener(handler)

        # Fallback: use default opener (respects env vars)
        return urllib.request.build_opener()

    def proxy_host_port(self) -> tuple[str, int] | None:
        """Parse proxy host and port for raw-socket (WebSocket) use."""
        if not self.proxy_url:
            return None
        try:
            from urllib.parse import urlparse

            p = urlparse(self.proxy_url)
            host = p.hostname
            port = p.port or 3128
            if host:
                return host, port
        except Exception:  # noqa: BLE001
            pass
        return None

    def summary(self) -> str:
        """One-line human-readable description."""
        if self.strategy == ProxyStrategy.DIRECT:
            return "direct (no proxy)"
        if self.strategy == ProxyStrategy.ENV:
            return f"env proxy ({self.proxy_url})"
        return f"wpad proxy ({self.proxy_url})"


class ProxyProbe:
    """Probe which proxy strategy (if any) can reach a GitLab host.

    The probe is intentionally lightweight: it makes a small HEAD/GET
    request to ``<host>/users/sign_in`` (a page that always exists on
    GitLab, even without auth) to confirm reachability.
    """

    def __init__(self, gitlab_host: str, timeout: int = PROBE_TIMEOUT) -> None:
        self.gitlab_host = gitlab_host.rstrip("/")
        self.timeout = timeout
        self.cached: ProbeResult | None = None

    def resolve(self, *, force: bool = False) -> ProbeResult:
        """Return a cached or freshly probed result."""
        if self.cached is not None and not force:
            return self.cached
        result = self.probe()
        self.cached = result
        return result

    # ------------------------------------------------------------------
    # internals

    def probe_url(self) -> str:
        """URL that is reliably accessible on any GitLab instance."""
        return f"{self.gitlab_host}/-/readiness"

    def try_connect(self, opener: urllib.request.OpenerDirector, label: str) -> bool:
        """Return True if we can GET the probe URL with this opener."""
        url = self.probe_url()
        try:
            req = urllib.request.Request(url, method="GET")
            with opener.open(req, timeout=self.timeout) as resp:
                ok = resp.status < 500
                logger.debug("proxy probe [%s] -> HTTP %d", label, resp.status)
                return ok
        except urllib.error.HTTPError as e:
            # 4xx still means we reached the server — proxy is working
            logger.debug("proxy probe [%s] -> HTTP %d (ok, server reachable)", label, e.code)
            return e.code < 500
        except Exception as exc:
            logger.debug("proxy probe [%s] -> failed: %s", label, exc)
            return False

    def wpad_url_candidates(self) -> list[str]:
        """Return WPAD URL candidates to try (classic + domain-appended)."""
        candidates = ["http://wpad/wpad.dat"]
        try:
            fqdn = socket.getfqdn()
            # Strip the host label to get the domain
            parts = fqdn.split(".")
            if len(parts) > 2:
                domain = ".".join(parts[1:])
                candidates.append(f"http://wpad.{domain}/wpad.dat")
        except Exception:  # noqa: BLE001
            pass
        return candidates

    def fetch_wpad(self) -> str | None:
        """Try to fetch a WPAD PAC file. Returns raw PAC text or None."""
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for url in self.wpad_url_candidates():
            try:
                with direct_opener.open(url, timeout=WPAD_TIMEOUT) as resp:
                    if resp.status == 200:
                        pac_text = resp.read(65536).decode("utf-8", errors="replace")
                        logger.debug("WPAD found at %s (%d bytes)", url, len(pac_text))
                        return pac_text
            except Exception:  # noqa: BLE001
                pass
        return None

    def parse_proxy_from_pac(self, pac_text: str, _url: str) -> str | None:
        """Very minimal PAC parser: extract first PROXY directive.

        A proper PAC evaluation requires a JS engine (the PAC file is
        JavaScript).  We do a best-effort text scan for ``PROXY host:port``
        patterns — sufficient for the common corporate case where the PAC
        file has a single explicit proxy with a direct fallback.
        """
        import re

        # Typical: return "PROXY proxy.corp.example.com:8080; DIRECT";
        matches = re.findall(r"\bPROXY\s+([\w.\-]+:\d+)", pac_text, re.IGNORECASE)
        if matches:
            return f"http://{matches[0]}"
        return None

    def probe(self) -> ProbeResult:
        env_vars = ProxyEnvVars.snapshot()
        notes: list[str] = []

        # ---- Strategy 1: env vars ----------------------------------------
        if env_vars.any_set():
            proxy_url = env_vars.effective_proxy()
            opener = (
                urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
                if proxy_url
                else urllib.request.build_opener()
            )
            if self.try_connect(opener, "env-proxy"):
                notes.append("Connected using env proxy vars.")
                logger.info("proxy probe: using env proxy %s", proxy_url)
                return ProbeResult(
                    strategy=ProxyStrategy.ENV,
                    proxy_url=proxy_url,
                    env_vars=env_vars,
                    notes=notes,
                )
            notes.append(f"Env proxy {proxy_url!r} did not reach GitLab — trying direct.")
            logger.info("proxy probe: env proxy failed, trying direct")

        # ---- Strategy 2: direct ------------------------------------------
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if self.try_connect(direct_opener, "direct"):
            notes.append("Direct connection succeeded (no proxy needed).")
            logger.info("proxy probe: direct connection works")
            return ProbeResult(
                strategy=ProxyStrategy.DIRECT,
                proxy_url=None,
                env_vars=env_vars,
                notes=notes,
            )
        notes.append("Direct connection failed — trying WPAD auto-discovery.")
        logger.info("proxy probe: direct failed, trying WPAD")

        # ---- Strategy 3: WPAD / PAC --------------------------------------
        pac_text = self.fetch_wpad()
        if pac_text:
            proxy_url = self.parse_proxy_from_pac(pac_text, self.gitlab_host)
            if proxy_url:
                wpad_opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
                )
                if self.try_connect(wpad_opener, "wpad"):
                    notes.append(f"WPAD auto-discovered proxy {proxy_url!r}.")
                    logger.info("proxy probe: WPAD proxy %s works", proxy_url)
                    return ProbeResult(
                        strategy=ProxyStrategy.WPAD,
                        proxy_url=proxy_url,
                        env_vars=env_vars,
                        notes=notes,
                    )
                notes.append(f"WPAD proxy {proxy_url!r} also failed to reach GitLab.")
            else:
                notes.append("WPAD found but could not parse a proxy address from PAC file.")
        else:
            notes.append("No WPAD file found on network.")

        # ---- All strategies failed — fall back to whatever env says ------
        # Return env if set (maybe the host is intermittently unreachable but
        # the proxy is still correct), otherwise direct.
        notes.append("All probe strategies failed; defaulting to best-guess.")
        if env_vars.any_set():
            logger.warning("proxy probe: all strategies failed, keeping env proxy as fallback")
            return ProbeResult(
                strategy=ProxyStrategy.ENV,
                proxy_url=env_vars.effective_proxy(),
                env_vars=env_vars,
                notes=notes,
            )
        logger.warning("proxy probe: all strategies failed, defaulting to direct")
        return ProbeResult(
            strategy=ProxyStrategy.DIRECT,
            proxy_url=None,
            env_vars=env_vars,
            notes=notes,
        )


# Module-level singleton so the probe runs at most once per process
session_probe: ProxyProbe | None = None
session_result: ProbeResult | None = None


def get_session_proxy(gitlab_host: str, *, force: bool = False) -> ProbeResult:
    """Run the proxy probe for *gitlab_host*, caching the result for the session.

    Subsequent calls with any host return the cached result — the assumption
    is that all traffic goes to a single GitLab instance.
    """
    global session_probe, session_result  # noqa: PLW0603
    if session_result is not None and not force:
        return session_result
    session_probe = ProxyProbe(gitlab_host)
    session_result = session_probe.resolve()
    return session_result


def clear_session_proxy() -> None:
    """Reset the session cache (used in tests)."""
    global session_probe, session_result  # noqa: PLW0603
    session_probe = None
    session_result = None
