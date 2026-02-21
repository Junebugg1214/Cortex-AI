"""
Pagination utilities for the CortexClient.

Provides an iterator that auto-fetches pages from cursor-based list endpoints.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator


class PaginatedIterator:
    """Lazy iterator over a cursor-paginated CaaS list endpoint.

    Fetches one page at a time. Yields individual items.
    """

    def __init__(
        self,
        fetch_page: Callable[[str, int, str | None], dict],
        method: str,
        path: str,
        limit: int = 20,
    ) -> None:
        self._fetch_page = fetch_page
        self._method = method
        self._path = path
        self._limit = limit
        self._cursor: str | None = None
        self._done = False

    def __iter__(self) -> Iterator[Any]:
        while not self._done:
            qs = f"?limit={self._limit}"
            if self._cursor:
                qs += f"&cursor={self._cursor}"
            data = self._fetch_page(self._method, self._path + qs)
            items = data.get("items", [])
            yield from items
            if not data.get("has_more", False):
                self._done = True
            else:
                self._cursor = data.get("next_cursor")
                if not self._cursor:
                    self._done = True
