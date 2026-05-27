"""URL safety validation and HTTP fetch for web attachments.

Uses only stdlib: urllib, socket, ssl, ipaddress.
No third-party HTTP libraries.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuochat.config import WebAttachConfig

logger = logging.getLogger("tuochat.web.fetch")

# Ports allowed unless the config overrides them
DEFAULT_ALLOWED_PORTS = {80, 443}

# Content-types we will accept and attempt to convert
ACCEPTED_CONTENT_TYPES = {"text/html", "text/plain"}

USER_AGENT = "tuochat/0 (web-attach; +https://gitlab.com/matthewdeanmartin/tuochat)"


@dataclass
class FetchResult:
    """Everything returned by a successful fetch."""

    url: str
    final_url: str
    status: int
    content_type: str
    charset: str
    body_bytes: bytes
    warnings: list[str]


class WebAttachError(Exception):
    """Raised when a fetch or safety check fails in a user-visible way."""


def check_url_safety(url: str, cfg: WebAttachConfig) -> None:
    """Validate URL against configured safety policy.

    Raises WebAttachError on any policy violation.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise WebAttachError(f"Could not parse URL: {exc}") from exc

    # Reject embedded credentials
    if parsed.username or parsed.password:
        raise WebAttachError("URLs with embedded credentials are not allowed.")

    scheme = (parsed.scheme or "").lower()

    if cfg.https_only and scheme != "https":
        raise WebAttachError(f"Only HTTPS URLs are allowed (https_only = true). Got scheme: {scheme!r}")

    if scheme not in {"http", "https"}:
        raise WebAttachError(f"Unsupported URL scheme: {scheme!r}. Only http and https are allowed.")

    host = parsed.hostname or ""
    if not host:
        raise WebAttachError("URL has no host.")

    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80

    allowed_ports = set(cfg.allowed_ports) if cfg.allowed_ports else DEFAULT_ALLOWED_PORTS
    if port not in allowed_ports:
        raise WebAttachError(
            f"Port {port} is not in the allowed list {sorted(allowed_ports)}. "
            "Change web_attach.allowed_ports in config to permit it."
        )

    if cfg.public_ip_only:
        check_host_is_public(host)


def check_host_is_public(host: str) -> None:
    """Resolve host and reject loopback/private/link-local/multicast/reserved addresses.

    Raises WebAttachError if any resolved address is non-public.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WebAttachError(f"DNS resolution failed for {host!r}: {exc}") from exc

    if not infos:
        raise WebAttachError(f"DNS returned no addresses for {host!r}.")

    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError as value_error:
            raise WebAttachError(f"Could not parse resolved address {addr_str!r} for {host!r}.") from value_error

        if addr.is_loopback:
            raise WebAttachError(f"Resolved address {addr_str} for {host!r} is loopback (public_ip_only = true).")
        if addr.is_private:
            raise WebAttachError(f"Resolved address {addr_str} for {host!r} is private (public_ip_only = true).")
        if addr.is_link_local:
            raise WebAttachError(f"Resolved address {addr_str} for {host!r} is link-local (public_ip_only = true).")
        if addr.is_multicast:
            raise WebAttachError(f"Resolved address {addr_str} for {host!r} is multicast (public_ip_only = true).")
        if addr.is_reserved:
            raise WebAttachError(f"Resolved address {addr_str} for {host!r} is reserved (public_ip_only = true).")

    logger.debug("check_host_is_public: %s resolved to %d address(es), all public", host, len(infos))


def build_ssl_context(cfg: WebAttachConfig) -> ssl.SSLContext:
    """Build an SSL context that honours tls13_only when set."""
    ctx = ssl.create_default_context()
    if cfg.tls13_only:
        # Experimental: require TLS 1.3 exclusively
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        logger.debug("build_ssl_context: TLS 1.3 only (experimental)")
    return ctx


def fetch_url(url: str, cfg: WebAttachConfig) -> FetchResult:
    """Fetch a single URL with safety checks applied before every redirect.

    Returns a FetchResult on success.
    Raises WebAttachError on policy violation or HTTP/network error.
    """
    check_url_safety(url, cfg)

    warnings: list[str] = []
    redirect_count = 0
    current_url = url
    ssl_ctx = build_ssl_context(cfg)

    # We do manual redirect handling so we can re-run safety checks on each hop
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_ctx))
    opener.addheaders = [("User-Agent", USER_AGENT)]

    while True:
        logger.debug("fetch_url: requesting %s (redirect %d)", current_url, redirect_count)

        request = urllib.request.Request(current_url, headers={"User-Agent": USER_AGENT})

        try:
            # Disable urllib's automatic redirect following so we can validate each hop
            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913
                    return None

            no_redirect_opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl_ctx),
                NoRedirectHandler(),
            )
            no_redirect_opener.addheaders = [("User-Agent", USER_AGENT)]

            response = no_redirect_opener.open(request, timeout=cfg.timeout_seconds)

        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location", "")
                if not location:
                    raise WebAttachError(f"Redirect (HTTP {exc.code}) with no Location header.") from exc
                if not cfg.follow_redirects:
                    raise WebAttachError(
                        f"HTTP {exc.code} redirect to {location!r} but follow_redirects = false."
                    ) from exc
                if redirect_count >= cfg.max_redirects:
                    raise WebAttachError(
                        f"Too many redirects (max {cfg.max_redirects}). Last redirect was to {location!r}."
                    ) from exc
                redirect_count += 1
                resolved = urllib.parse.urljoin(current_url, location)
                logger.debug("fetch_url: redirect %d -> %s", redirect_count, resolved)
                check_url_safety(resolved, cfg)
                current_url = resolved
                continue
            raise WebAttachError(f"HTTP {exc.code} {exc.reason} for {current_url}") from exc

        except urllib.error.URLError as exc:
            raise WebAttachError(f"Network error fetching {current_url}: {exc.reason}") from exc

        # Successful response
        final_url = response.url or current_url
        status = response.status

        raw_content_type = response.headers.get("Content-Type", "")
        content_type, charset = parse_content_type(raw_content_type)

        if content_type not in ACCEPTED_CONTENT_TYPES:
            response.close()
            raise WebAttachError(
                f"Content-Type {content_type!r} is not supported. "
                f"Only {sorted(ACCEPTED_CONTENT_TYPES)} are accepted."
            )

        try:
            body_bytes = response.read(cfg.max_response_bytes + 1)
        finally:
            response.close()

        if len(body_bytes) > cfg.max_response_bytes:
            warnings.append(f"content truncated at {cfg.max_response_bytes:,} bytes")
            body_bytes = body_bytes[: cfg.max_response_bytes]

        logger.debug(
            "fetch_url: fetched %s -> %s, %d bytes, content-type=%s",
            url,
            final_url,
            len(body_bytes),
            content_type,
        )

        return FetchResult(
            url=url,
            final_url=final_url,
            status=status,
            content_type=content_type,
            charset=charset or "utf-8",
            body_bytes=body_bytes,
            warnings=warnings,
        )


def parse_content_type(raw: str) -> tuple[str, str]:
    """Parse a Content-Type header into (media_type, charset).

    Returns empty strings for missing or malformed values.
    """
    if not raw:
        return "", ""
    parts = [p.strip() for p in raw.split(";")]
    media_type = parts[0].lower()
    charset = ""
    for part in parts[1:]:
        if part.lower().startswith("charset="):
            charset = part[8:].strip().strip('"').strip("'")
            break
    return media_type, charset
