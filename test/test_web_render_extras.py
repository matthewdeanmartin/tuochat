from __future__ import annotations

from types import SimpleNamespace

import tuochat.web.render as web_render


def test_extract_html_stdlib_covers_inline_media_and_decode_fallback():
    body = b"""<!doctype html>
<html>
  <head><title>Inline tags</title></head>
  <body>
    <p><strong>Bold</strong> and <em>italic</em> with <code>code</code>.</p>
    <hr>
    <img alt="Diagram" src="/diagram.png">
    <a>Plain anchor</a>
  </body>
</html>"""

    markdown, metadata = web_render.extract_html_stdlib(body, "not-a-charset")

    assert metadata.title == "Inline tags"
    assert "**Bold**" in markdown
    assert "*italic*" in markdown
    assert "`code`" in markdown
    assert "---" in markdown
    assert "![Diagram](/diagram.png)" in markdown
    assert "Plain anchor" in markdown


def test_optional_extractors_work_with_lightweight_fake_modules(monkeypatch):
    trafilatura_module = SimpleNamespace(extract=lambda *args, **kwargs: SimpleNamespace(text="Trafilatura body"))

    class FakeDocument:
        def __init__(self, text: str):
            self.text = text

        def title(self) -> str:
            return "Readable title"

        def summary(self, html_partial: bool = True) -> str:  # noqa: FBT001, ARG002
            return "<p>Readable summary</p>"

    class FakeHTML2Text:
        ignore_links = False
        ignore_images = True
        body_width = 0

        def handle(self, text: str) -> str:  # noqa: ARG002
            return "Converted markdown"

    monkeypatch.setitem(__import__("sys").modules, "trafilatura", trafilatura_module)
    monkeypatch.setitem(__import__("sys").modules, "readability", SimpleNamespace(Document=FakeDocument))
    monkeypatch.setitem(__import__("sys").modules, "html2text", SimpleNamespace(HTML2Text=FakeHTML2Text))

    html = b"""<html><head><title>Fallback title</title><meta name="description" content="Desc"></head>
<body><p>Body text</p></body></html>"""

    trafilatura_result = web_render.extract_html_trafilatura(html, "utf-8")
    readability_result = web_render.extract_html_readability(html, "utf-8")
    html2text_result = web_render.extract_html_html2text(html, "utf-8")

    assert trafilatura_result == (
        "Trafilatura body",
        web_render.PageMetadata(title="Fallback title", description="Desc"),
    )
    assert readability_result is not None
    assert readability_result[0] == "Readable summary"
    assert readability_result[1].title == "Fallback title"
    assert html2text_result == (
        "Converted markdown",
        web_render.PageMetadata(title="Fallback title", description="Desc"),
    )


def test_run_engine_chain_falls_back_and_render_page_uses_default_order(monkeypatch):
    monkeypatch.setitem(web_render.ENGINE_EXTRACTORS, "fake", lambda html_bytes, charset: None)

    content, metadata, engine_name = web_render.run_engine_chain(
        b"<html><body>Fallback body</body></html>", "utf-8", ["fake"]
    )
    default_page = web_render.render_page(
        body_bytes=b"<html><body>Default order works</body></html>",
        content_type="text/html",
        charset="utf-8",
        max_attachment_chars=100,
        engine_order=None,
    )
    plain_text, plain_meta = web_render.extract_plain_text(b"plain text", "utf-8")

    assert engine_name == "stdlib"
    assert "Fallback body" in content
    assert metadata == web_render.PageMetadata()
    assert default_page.engine_used == "stdlib"
    assert default_page.markdown == "Default order works"
    assert plain_text == "plain text"
    assert plain_meta == web_render.PageMetadata()
