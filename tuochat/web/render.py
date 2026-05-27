"""HTML-to-Markdown conversion pipeline for web attachments.

Engine ladder (tried in config order, first to return non-empty content wins):
  "trafilatura"  — best extraction quality; optional dep (pip install tuochat[web])
  "readability"  — readability-lxml; optional dep (pip install tuochat[web])
  "html2text"    — html2text; optional dep (pip install tuochat[web])
  "stdlib"       — built-in stdlib fallback, always available

Each engine degrades gracefully: if the package is not installed, the engine is
skipped and the next one in the chain is tried.
"""

from __future__ import annotations

import html
import html.parser
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("tuochat.web.render")


@dataclass
class PageMetadata:
    """Metadata extracted from a fetched page."""

    title: str = ""
    description: str = ""
    canonical_url: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class RenderedPage:
    """Output of the conversion pipeline."""

    markdown: str
    metadata: PageMetadata
    engine_used: str
    char_count: int


class SimpleHTMLExtractor(html.parser.HTMLParser):
    """Minimal pull-parser that strips scripts/styles and renders readable text.

    Output is plain text suitable for lightweight markdown wrapping.
    This is the stdlib fallback engine — deliberately simple and dependency-free.
    """

    # Tags whose full subtree we discard entirely
    # Note: <head> is NOT here — we need it to reach <title> and <meta>.
    SKIP_TAGS = frozenset(
        {
            "script",
            "style",
            "noscript",
            "nav",
            "footer",
            "aside",
            "form",
            "button",
            "iframe",
            "svg",
            "canvas",
            "template",
            "object",
            "embed",
        }
    )

    # Block-level tags that get a blank line before and after
    BLOCK_TAGS = frozenset(
        {
            "p",
            "div",
            "section",
            "article",
            "main",
            "header",
            "blockquote",
            "pre",
            "ul",
            "ol",
            "li",
            "dl",
            "dt",
            "dd",
            "table",
            "tr",
            "td",
            "th",
            "caption",
            "figure",
            "figcaption",
        }
    )

    HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.skip_depth: int = 0
        self.heading_level: int = 0
        self.in_pre: bool = False
        self.in_li: bool = False
        self.in_head: bool = False
        self.metadata = PageMetadata()
        self.in_title: bool = False
        self.current_href: str = ""
        self.in_anchor: bool = False
        self.anchor_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth > 0:
            if tag in self.SKIP_TAGS:
                self.skip_depth += 1
            return

        if tag in self.SKIP_TAGS:
            self.skip_depth = 1
            return

        attr_dict = dict(attrs)

        if tag == "head":
            self.in_head = True
            return

        if tag == "title":
            self.in_title = True
            return

        if tag == "meta":
            name = (attr_dict.get("name") or attr_dict.get("property") or "").lower()
            content = attr_dict.get("content") or ""
            if name in {"description", "og:description"} and not self.metadata.description:
                self.metadata.description = content.strip()
            if name == "og:title" and not self.metadata.title:
                self.metadata.title = content.strip()
            return

        if tag == "link":
            rel = (attr_dict.get("rel") or "").lower()
            href = attr_dict.get("href") or ""
            if rel == "canonical" and href:
                self.metadata.canonical_url = href.strip()
            return

        if tag in self.HEADING_TAGS:
            level = int(tag[1])
            self.heading_level = level
            self.chunks.append(f"\n\n{'#' * level} ")
            return

        if tag == "a":
            self.current_href = attr_dict.get("href") or ""
            self.in_anchor = True
            self.anchor_text_parts = []
            return

        if tag == "br":
            self.chunks.append("\n")
            return

        if tag == "pre":
            self.in_pre = True
            self.chunks.append("\n\n```\n")
            return

        if tag == "code" and not self.in_pre:
            self.chunks.append("`")
            return

        if tag in ("strong", "b"):
            self.chunks.append("**")
            return

        if tag in ("em", "i"):
            self.chunks.append("*")
            return

        if tag == "li":
            self.chunks.append("\n- ")
            self.in_li = True
            return

        if tag in self.BLOCK_TAGS:
            self.chunks.append("\n\n")
            return

        if tag == "hr":
            self.chunks.append("\n\n---\n\n")
            return

        if tag == "img":
            alt = attr_dict.get("alt") or ""
            src = attr_dict.get("src") or ""
            if alt:
                self.chunks.append(f"![{alt}]({src})")
            return

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth > 0:
            if tag in self.SKIP_TAGS:
                self.skip_depth -= 1
            return

        if tag == "head":
            self.in_head = False
            return

        if tag == "title":
            self.in_title = False
            return

        if tag in self.HEADING_TAGS:
            self.heading_level = 0
            self.chunks.append("\n\n")
            return

        if tag == "a":
            text = "".join(self.anchor_text_parts).strip()
            href = self.current_href
            if text and href:
                self.chunks.append(f"[{text}]({href})")
            elif text:
                self.chunks.append(text)
            self.in_anchor = False
            self.anchor_text_parts = []
            self.current_href = ""
            return

        if tag in self.BLOCK_TAGS:
            self.chunks.append("\n\n")
            return

        if tag == "pre":
            self.in_pre = False
            self.chunks.append("\n```\n\n")
            return

        if tag == "code" and not self.in_pre:
            self.chunks.append("`")
            return

        if tag in {"strong", "b"}:
            self.chunks.append("**")
            return

        if tag in {"em", "i"}:
            self.chunks.append("*")
            return

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return

        if self.in_title:
            self.metadata.title += data
            return

        # Suppress any other text that appears inside <head>
        if self.in_head:
            return

        text = html.unescape(data)

        if self.in_pre:
            self.chunks.append(text)
            return

        if self.in_anchor:
            self.anchor_text_parts.append(text)
            # Text is emitted at end-anchor as [text](href); don't double-emit
            return

        if text.strip():
            self.chunks.append(text)

    def result(self) -> str:
        """Return the assembled text output."""
        raw = "".join(self.chunks)
        # Collapse excessive blank lines
        cleaned = re.sub(r"\n{3,}", "\n\n", raw)
        return cleaned.strip()


def extract_html_stdlib(html_bytes: bytes, charset: str) -> tuple[str, PageMetadata]:
    """Parse HTML with stdlib and return (markdown_text, metadata)."""
    try:
        text = html_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = html_bytes.decode("utf-8", errors="replace")

    extractor = SimpleHTMLExtractor()
    try:
        extractor.feed(text)
    except Exception as exc:
        logger.warning("HTML parser raised during extraction: %s", exc)

    return extractor.result(), extractor.metadata


def extract_metadata_stdlib(html_bytes: bytes, charset: str) -> PageMetadata:
    """Extract only page metadata (title, description, canonical) using stdlib.

    Used to supplement third-party engine output with metadata they may miss.
    """
    try:
        text = html_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = html_bytes.decode("utf-8", errors="replace")

    extractor = SimpleHTMLExtractor()
    try:
        extractor.feed(text)
    except Exception:
        pass
    return extractor.metadata


def extract_html_trafilatura(html_bytes: bytes, charset: str) -> tuple[str, PageMetadata] | None:
    """Extract main content using trafilatura (optional dep).

    Returns None if trafilatura is not installed or extraction fails.
    """
    try:
        import trafilatura  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("extract_html_trafilatura: trafilatura not installed, skipping")
        return None

    try:
        text = html_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = html_bytes.decode("utf-8", errors="replace")

    try:
        result = trafilatura.extract(
            text,
            include_links=True,
            include_images=False,
            output_format="markdown",
            no_fallback=False,
            with_metadata=True,
        )
    except Exception as exc:
        logger.warning("trafilatura extraction failed: %s", exc)
        return None

    if not result:
        return None

    # trafilatura may return a metadata-enriched object or plain str depending on version
    if hasattr(result, "text"):
        content = result.text or ""
    else:
        content = str(result)

    content = content.strip()
    if not content:
        return None

    # Supplement with stdlib metadata for title/description/canonical
    meta = extract_metadata_stdlib(html_bytes, charset)
    return content, meta


def extract_html_readability(html_bytes: bytes, charset: str) -> tuple[str, PageMetadata] | None:
    """Extract main content using readability-lxml (optional dep).

    Returns None if readability-lxml is not installed or extraction fails.
    """
    try:
        from readability import Document  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("extract_html_readability: readability-lxml not installed, skipping")
        return None

    try:
        text = html_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = html_bytes.decode("utf-8", errors="replace")

    try:
        doc = Document(text)
        title = doc.title() or ""
        summary_html = doc.summary(html_partial=True)
    except Exception as exc:
        logger.warning("readability extraction failed: %s", exc)
        return None

    if not summary_html or not summary_html.strip():
        return None

    # Convert readability output (HTML fragment) through stdlib extractor
    summary_bytes = summary_html.encode("utf-8")
    content, _ = extract_html_stdlib(summary_bytes, "utf-8")
    content = content.strip()
    if not content:
        return None

    meta = extract_metadata_stdlib(html_bytes, charset)
    if title and not meta.title:
        meta.title = title.strip()
    return content, meta


def extract_html_html2text(html_bytes: bytes, charset: str) -> tuple[str, PageMetadata] | None:
    """Extract content using html2text (optional dep).

    Returns None if html2text is not installed or extraction fails.
    """
    try:
        import html2text as h2t  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("extract_html_html2text: html2text not installed, skipping")
        return None

    try:
        text = html_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = html_bytes.decode("utf-8", errors="replace")

    try:
        handler = h2t.HTML2Text()
        handler.ignore_links = False
        handler.ignore_images = True
        handler.body_width = 0  # no line wrapping
        content = handler.handle(text).strip()
    except Exception as exc:
        logger.warning("html2text extraction failed: %s", exc)
        return None

    if not content:
        return None

    meta = extract_metadata_stdlib(html_bytes, charset)
    return content, meta


# Registry maps engine name → extractor function
ENGINE_EXTRACTORS = {
    "trafilatura": extract_html_trafilatura,
    "readability": extract_html_readability,
    "html2text": extract_html_html2text,
    "stdlib": None,  # handled separately — always available
}


def run_engine_chain(
    html_bytes: bytes,
    charset: str,
    engine_order: list[str],
) -> tuple[str, PageMetadata, str]:
    """Try engines in order and return (content, metadata, engine_name) for first hit.

    Falls back to stdlib if all others fail or are unavailable.
    """
    for engine_name in engine_order:
        if engine_name == "stdlib":
            content, meta = extract_html_stdlib(html_bytes, charset)
            if content:
                logger.debug("run_engine_chain: stdlib succeeded")
                return content, meta, "stdlib"
            continue

        extractor = ENGINE_EXTRACTORS.get(engine_name)
        if extractor is None:
            logger.debug("run_engine_chain: unknown engine %r, skipping", engine_name)
            continue

        result = extractor(html_bytes, charset)
        if result is not None:
            content, meta = result
            if content:
                logger.debug("run_engine_chain: %s succeeded", engine_name)
                return content, meta, engine_name

    # Guaranteed fallback
    logger.debug("run_engine_chain: all engines failed or skipped, using stdlib")
    content, meta = extract_html_stdlib(html_bytes, charset)
    return content, meta, "stdlib"


def extract_plain_text(text_bytes: bytes, charset: str) -> tuple[str, PageMetadata]:
    """Handle text/plain responses — just decode and return."""
    try:
        text = text_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = text_bytes.decode("utf-8", errors="replace")
    return text.strip(), PageMetadata()


def render_page(
    body_bytes: bytes,
    content_type: str,
    charset: str,
    max_attachment_chars: int,
    engine_order: list[str] | None = None,
) -> RenderedPage:
    """Run the extraction + markdown pipeline and return a RenderedPage.

    engine_order overrides the config default when provided (per-command override).
    Falls back to ["stdlib"] when None.
    """
    warnings: list[str] = []

    def add_warning(text: str) -> None:
        warnings.append(text)
        metadata.warnings.append(text)

    if content_type == "text/plain":
        markdown, metadata = extract_plain_text(body_bytes, charset)
        engine_used = "plain"
    else:
        effective_order = engine_order if engine_order is not None else ["stdlib"]
        markdown, metadata, engine_used = run_engine_chain(body_bytes, charset, effective_order)

    # Check for javascript-heavy pages (heuristic)
    if content_type == "text/html" and len(markdown.strip()) < 200 and len(body_bytes) > 5000:
        add_warning("javascript-heavy page — content may be incomplete")

    if len(markdown) > max_attachment_chars:
        add_warning(f"content truncated at {max_attachment_chars:,} chars")
        markdown = markdown[:max_attachment_chars]

    return RenderedPage(
        markdown=markdown,
        metadata=metadata,
        engine_used=engine_used,
        char_count=len(markdown),
    )
