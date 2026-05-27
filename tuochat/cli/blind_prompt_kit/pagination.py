"""Pagination primitives for chunked reading."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from typing import Generic, TypeVar

ItemT = TypeVar("ItemT")


@dataclass(frozen=True)
class Page(Generic[ItemT]):
    """A single page of items."""

    items: Sequence[ItemT]
    number: int
    total_pages: int
    start_index: int
    end_index: int
    total_items: int


@dataclass
class Pager(Generic[ItemT]):
    """Stateful page navigation."""

    items: Sequence[ItemT]
    page_size: int = 5
    page_number: int = 1

    def total_pages(self) -> int:
        """Return the number of available pages."""
        if not self.items:
            return 1
        return max(1, ceil(len(self.items) / self.page_size))

    def current(self) -> Page[ItemT]:
        """Return the current page."""
        total_items = len(self.items)
        total_pages = self.total_pages()
        page_number = min(max(self.page_number, 1), total_pages)
        start = (page_number - 1) * self.page_size
        end = min(start + self.page_size, total_items)
        return Page(
            items=self.items[start:end],
            number=page_number,
            total_pages=total_pages,
            start_index=start,
            end_index=end,
            total_items=total_items,
        )

    def next(self) -> Page[ItemT]:
        """Advance to the next page."""
        self.page_number = min(self.page_number + 1, self.total_pages())
        return self.current()

    def prev(self) -> Page[ItemT]:
        """Move to the previous page."""
        self.page_number = max(1, self.page_number - 1)
        return self.current()

    def first(self) -> Page[ItemT]:
        """Move to the first page."""
        self.page_number = 1
        return self.current()

    def last(self) -> Page[ItemT]:
        """Move to the last page."""
        self.page_number = self.total_pages()
        return self.current()

    def go_to(self, page_number: int) -> Page[ItemT]:
        """Jump to a specific page."""
        self.page_number = min(max(page_number, 1), self.total_pages())
        return self.current()

    def resize(self, page_size: int) -> Page[ItemT]:
        """Change page size and preserve the first visible item."""
        current = self.current()
        first_visible_index = current.start_index
        self.page_size = max(1, page_size)
        self.page_number = max(1, (first_visible_index // self.page_size) + 1)
        return self.current()
