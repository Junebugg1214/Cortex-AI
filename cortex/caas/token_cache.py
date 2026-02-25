"""
LRU + TTL cache for verified grant tokens.

Caches the decoded token data keyed on the raw token string to avoid
repeating Ed25519 verification + base64 decode + JSON parse on every
request.  Thread-safe via a threading.Lock.

Grant revocation checks are NOT cached — they are always performed
after the cache lookup to ensure revoked grants are rejected immediately.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class TokenCache:
    """LRU cache with per-entry TTL for decoded grant tokens.

    Parameters:
        max_size: Maximum number of cached entries (default 1024).
        ttl: Time-to-live in seconds for each entry (default 30).
    """

    def __init__(self, max_size: int = 1024, ttl: float = 30.0) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, token_str: str) -> Any | None:
        """Return cached token data if present and not expired, else None."""
        with self._lock:
            entry = self._cache.get(token_str)
            if entry is None:
                return None
            data, expires_at = entry
            if time.monotonic() > expires_at:
                del self._cache[token_str]
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(token_str)
            return data

    def put(self, token_str: str, token_data: Any) -> None:
        """Cache token data with TTL. Evicts LRU entry if at capacity."""
        with self._lock:
            if token_str in self._cache:
                self._cache.move_to_end(token_str)
            self._cache[token_str] = (token_data, time.monotonic() + self._ttl)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, token_str: str) -> bool:
        """Remove a specific entry. Returns True if it was present."""
        with self._lock:
            if token_str in self._cache:
                del self._cache[token_str]
                return True
            return False

    def clear(self) -> None:
        """Remove all cached entries."""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        """Current number of cached entries."""
        with self._lock:
            return len(self._cache)
