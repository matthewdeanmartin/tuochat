"""High-level web attachment API — fetch, render, and format for chat context."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tuochat.web.fetch import FetchResult, WebAttachError, fetch_url  # noqa: F401  # pylint: disable=unused-import
from tuochat.web.render import RenderedPage, render_page

if TYPE_CHECKING:
    from tuochat.config import WebAttachConfig

logger = logging.getLogger("tuochat.web.attach")


@dataclass
class WebAttachment:
    """Everything needed to queue a web page as a chat attachment."""

    url: str
    fetch: FetchResult
    page: RenderedPage
    attachment_text: str


def fetch_and_render(url: str, cfg: WebAttachConfig, engine_override: str | None = None) -> WebAttachment:
    """Fetch a URL and convert it to markdown, honouring all config policies.

    engine_override: if set, use this single engine instead of cfg.engine_order.
    Raises WebAttachError on any policy violation or network error.
    """
    fetch_result = fetch_url(url, cfg)
    engine_order = [engine_override] if engine_override else list(cfg.engine_order)
    page = render_page(
        body_bytes=fetch_result.body_bytes,
        content_type=fetch_result.content_type,
        charset=fetch_result.charset,
        max_attachment_chars=cfg.max_attachment_chars,
        engine_order=engine_order,
    )

    all_warnings = list(fetch_result.warnings) + list(page.metadata.warnings)
    attachment_text = format_attachment(url, fetch_result, page, all_warnings)

    return WebAttachment(
        url=url,
        fetch=fetch_result,
        page=page,
        attachment_text=attachment_text,
    )


def format_attachment(
    url: str,
    fetch_result: FetchResult,
    page: RenderedPage,
    warnings: list[str],
) -> str:
    """Render the full attachment string that gets queued for the next request."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        "<!-- web-attach metadata -->",
        f"source_url: {url}",
    ]
    if fetch_result.final_url != url:
        lines.append(f"final_url: {fetch_result.final_url}")
    if page.metadata.canonical_url and page.metadata.canonical_url not in {url, fetch_result.final_url}:
        lines.append(f"canonical_url: {page.metadata.canonical_url}")
    if page.metadata.title:
        lines.append(f"title: {page.metadata.title.strip()}")
    if page.metadata.description:
        lines.append(f"description: {page.metadata.description.strip()}")
    lines.append(f"fetch_time: {now}")
    lines.append(f"content_type: {fetch_result.content_type}")
    lines.append(f"engine: {page.engine_used}")
    lines.append(f"chars: {page.char_count:,}")
    if warnings:
        lines.append(f"warnings: {'; '.join(warnings)}")
    lines.append("<!-- end metadata -->")
    lines.append("")
    lines.append(page.markdown)

    return "\n".join(lines)


def format_preview(url: str, fetch_result: FetchResult, page: RenderedPage, preview_chars: int) -> str:
    """Return a short human-readable preview for /web-preview confirmation."""
    lines: list[str] = [
        f"URL:          {url}",
    ]
    if fetch_result.final_url != url:
        lines.append(f"Final URL:    {fetch_result.final_url}")
    title = page.metadata.title.strip() or "(no title)"
    lines.append(f"Title:        {title}")
    lines.append(f"Content-type: {fetch_result.content_type}")
    lines.append(f"Engine:       {page.engine_used}")
    lines.append(f"Size (chars): {page.char_count:,}")

    all_warnings = list(fetch_result.warnings) + list(page.metadata.warnings)
    if all_warnings:
        lines.append(f"Warnings:     {'; '.join(all_warnings)}")

    lines.append("")
    snippet = page.markdown[:preview_chars].strip()
    if len(page.markdown) > preview_chars:
        snippet += "\n…"
    lines.append(snippet)

    return "\n".join(lines)
