"""
UPAI Pagination — Cursor-based pagination for collection endpoints.

Cursors are opaque base64-encoded strings containing the sort value and item ID.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any


@dataclass
class Page:
    """A page of results with cursor for next page."""

    items: list[dict]
    cursor: str | None   # None = no more pages
    has_more: bool
    total: int | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "items": self.items,
            "has_more": self.has_more,
        }
        if self.cursor is not None:
            d["cursor"] = self.cursor
        if self.total is not None:
            d["total"] = self.total
        return d


def encode_cursor(sort_value: str, item_id: str) -> str:
    """Encode sort value and item ID into an opaque cursor string."""
    payload = json.dumps({"s": sort_value, "i": item_id}, sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """Decode an opaque cursor into (sort_value, item_id)."""
    # Add padding only if needed: (4 - len % 4) % 4 gives 0,3,2,1 for len%4 = 0,1,2,3
    padded = cursor + "=" * ((4 - len(cursor) % 4) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    return payload["s"], payload["i"]


def paginate(
    items: list[dict],
    limit: int = 20,
    cursor: str | None = None,
    sort_key: str = "id",
) -> Page:
    """Paginate a list of dicts with cursor-based navigation.

    Items should already be sorted by sort_key. If cursor is provided,
    results start after the cursor position.
    """
    limit = max(1, min(limit, 100))  # clamp to 1-100

    # Find start position from cursor
    start_idx = 0
    if cursor:
        try:
            cursor_sort, cursor_id = decode_cursor(cursor)
            for i, item in enumerate(items):
                item_sort = str(item.get(sort_key, ""))
                item_id = str(item.get("id", ""))
                if item_sort == cursor_sort and item_id == cursor_id:
                    start_idx = i + 1
                    break
        except Exception:
            pass  # invalid cursor, start from beginning

    # Slice
    page_items = items[start_idx:start_idx + limit]
    has_more = start_idx + limit < len(items)

    # Build next cursor
    next_cursor = None
    if has_more and page_items:
        last = page_items[-1]
        next_cursor = encode_cursor(
            str(last.get(sort_key, "")),
            str(last.get("id", "")),
        )

    return Page(
        items=page_items,
        cursor=next_cursor,
        has_more=has_more,
        total=len(items),
    )
