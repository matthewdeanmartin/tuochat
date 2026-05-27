from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from tuochat.config import WebAttachConfig
from tuochat.web.attach import fetch_and_render, format_attachment, format_preview
from tuochat.web.fetch import (
    FetchResult,
    WebAttachError,
    check_host_is_public,
    check_url_safety,
    fetch_url,
    parse_content_type,
)
from tuochat.web.render import PageMetadata, RenderedPage, render_page


@contextmanager
def run_test_server():
    html_body = b"""<!doctype html>
<html>
  <head>
    <title>Example page</title>
    <meta name="description" content="Example description">
    <link rel="canonical" href="https://example.test/canonical">
  </head>
  <body>
    <h1>Heading</h1>
    <p>Alpha <a href="/docs">docs</a> text.</p>
    <ul><li>One</li><li>Two</li></ul>
    <pre>code block</pre>
    <script>ignored()</script>
  </body>
</html>"""
    plain_body = b"line one\nline two\nline three\n"
    json_body = b'{"ok": true}'
    large_body = b"x" * 64

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/plain")
                self.end_headers()
                return
            if self.path == "/html":
                body = html_body
                content_type = "text/html; charset=utf-8"
            elif self.path == "/plain":
                body = plain_body
                content_type = "text/plain; charset=utf-8"
            elif self.path == "/json":
                body = json_body
                content_type = "application/json"
            elif self.path == "/large":
                body = large_body
                content_type = "text/plain; charset=utf-8"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def make_web_cfg(port: int, **overrides: object) -> WebAttachConfig:
    cfg = WebAttachConfig(
        https_only=False,
        public_ip_only=False,
        allowed_ports=[port],
        timeout_seconds=5,
        max_response_bytes=1024,
        max_attachment_chars=500,
        preview_chars=80,
        engine_order=["stdlib"],
        follow_redirects=True,
        max_redirects=3,
    )
    for name, value in overrides.items():
        setattr(cfg, name, value)
    return cfg


def test_check_url_safety_rejects_unsafe_inputs():
    cfg = WebAttachConfig(https_only=False, public_ip_only=False, allowed_ports=[80, 443, 8080])

    with pytest.raises(WebAttachError, match="embedded credentials"):
        check_url_safety("https://user:pass@example.com", cfg)

    with pytest.raises(WebAttachError, match="Unsupported URL scheme"):
        check_url_safety("file:///tmp/example.html", cfg)

    with pytest.raises(WebAttachError, match="URL has no host"):
        check_url_safety("https:///missing-host", cfg)

    with pytest.raises(WebAttachError, match="Port 81 is not in the allowed list"):
        check_url_safety("https://example.com:81", cfg)


def test_check_host_is_public_rejects_loopback():
    with pytest.raises(WebAttachError, match="loopback"):
        check_host_is_public("127.0.0.1")


def test_parse_content_type_handles_charset_and_quotes():
    assert parse_content_type('text/html; charset="utf-8"') == ("text/html", "utf-8")
    assert parse_content_type("text/plain; charset='latin-1'") == ("text/plain", "latin-1")
    assert parse_content_type("") == ("", "")


def test_fetch_url_follows_redirects_and_truncates_response():
    with run_test_server() as base_url:
        port = int(base_url.rsplit(":", 1)[1])
        cfg = make_web_cfg(port, max_response_bytes=10)

        result = fetch_url(f"{base_url}/redirect", cfg)

    assert result.status == 200
    assert result.final_url == f"{base_url}/plain"
    assert result.content_type == "text/plain"
    assert result.charset == "utf-8"
    assert result.body_bytes == b"line one\nl"
    assert result.warnings == ["content truncated at 10 bytes"]


def test_fetch_url_rejects_unsupported_content_type():
    with run_test_server() as base_url:
        port = int(base_url.rsplit(":", 1)[1])
        cfg = make_web_cfg(port)

        with pytest.raises(WebAttachError, match="Content-Type 'application/json' is not supported"):
            fetch_url(f"{base_url}/json", cfg)


def test_render_page_extracts_stdlib_metadata_and_markdown():
    body = b"""<!doctype html>
<html>
  <head>
    <title>Title Here</title>
    <meta name="description" content="Short summary">
    <link rel="canonical" href="https://example.test/final">
  </head>
  <body>
    <h2>Section</h2>
    <p>Visit <a href="/help">help</a> now.</p>
    <ul><li>First</li><li>Second</li></ul>
    <pre>print('hi')</pre>
  </body>
</html>"""

    page = render_page(
        body_bytes=body,
        content_type="text/html",
        charset="utf-8",
        max_attachment_chars=1_000,
        engine_order=["unknown", "stdlib"],
    )

    assert page.engine_used == "stdlib"
    assert page.metadata.title == "Title Here"
    assert page.metadata.description == "Short summary"
    assert page.metadata.canonical_url == "https://example.test/final"
    assert "## Section" in page.markdown
    assert "[help](/help)" in page.markdown
    assert "- First" in page.markdown
    assert "```" in page.markdown


def test_render_page_adds_javascript_warning_and_truncates():
    body = ("<html><body>short" + ("<script>let x = 1;</script>" * 300) + "</body></html>").encode("utf-8")

    page = render_page(
        body_bytes=body,
        content_type="text/html",
        charset="utf-8",
        max_attachment_chars=3,
        engine_order=["stdlib"],
    )

    assert page.markdown == "sho"
    assert page.char_count == 3
    assert "javascript-heavy page" in page.metadata.warnings[0]
    assert "content truncated at 3 chars" in page.metadata.warnings[1]


def test_format_attachment_and_preview_include_metadata():
    fetch_result = FetchResult(
        url="https://example.test/source",
        final_url="https://example.test/final",
        status=200,
        content_type="text/html",
        charset="utf-8",
        body_bytes=b"<html></html>",
        warnings=["fetch warning"],
    )
    page = RenderedPage(
        markdown="alpha beta gamma delta",
        metadata=PageMetadata(
            title=" Example title ",
            description=" Example description ",
            canonical_url="https://example.test/canonical",
            warnings=["render warning"],
        ),
        engine_used="stdlib",
        char_count=22,
    )

    attachment = format_attachment(
        "https://example.test/source", fetch_result, page, ["fetch warning", "render warning"]
    )
    preview = format_preview("https://example.test/source", fetch_result, page, preview_chars=10)

    assert "final_url: https://example.test/final" in attachment
    assert "canonical_url: https://example.test/canonical" in attachment
    assert "title: Example title" in attachment
    assert "description: Example description" in attachment
    assert "warnings: fetch warning; render warning" in attachment
    assert attachment.endswith("alpha beta gamma delta")

    assert "Final URL:    https://example.test/final" in preview
    assert "Warnings:     fetch warning; render warning" in preview
    assert preview.endswith("alpha beta\n…")


def test_fetch_and_render_uses_builtin_http_server_end_to_end():
    with run_test_server() as base_url:
        port = int(base_url.rsplit(":", 1)[1])
        cfg = make_web_cfg(port, max_attachment_chars=200)

        result = fetch_and_render(f"{base_url}/html", cfg, engine_override="stdlib")

    assert result.fetch.content_type == "text/html"
    assert result.page.metadata.title == "Example page"
    assert result.page.engine_used == "stdlib"
    assert "source_url:" in result.attachment_text
    assert "Heading" in result.attachment_text
