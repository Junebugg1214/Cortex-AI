"""Tests for cortex.caas.token_cache — LRU + TTL token verification cache."""

import threading
import time
from unittest.mock import patch

from cortex.caas.token_cache import TokenCache


class TestTokenCacheBasics:

    def test_put_and_get(self):
        cache = TokenCache(max_size=10, ttl=60)
        cache.put("tok1", {"grant_id": "g1", "scope": "read"})
        result = cache.get("tok1")
        assert result == {"grant_id": "g1", "scope": "read"}

    def test_get_missing_returns_none(self):
        cache = TokenCache()
        assert cache.get("nonexistent") is None

    def test_size_property(self):
        cache = TokenCache()
        assert cache.size == 0
        cache.put("tok1", {"data": 1})
        assert cache.size == 1
        cache.put("tok2", {"data": 2})
        assert cache.size == 2

    def test_clear(self):
        cache = TokenCache()
        cache.put("tok1", {"data": 1})
        cache.put("tok2", {"data": 2})
        cache.clear()
        assert cache.size == 0
        assert cache.get("tok1") is None

    def test_invalidate_existing(self):
        cache = TokenCache()
        cache.put("tok1", {"data": 1})
        assert cache.invalidate("tok1") is True
        assert cache.get("tok1") is None
        assert cache.size == 0

    def test_invalidate_missing(self):
        cache = TokenCache()
        assert cache.invalidate("nonexistent") is False

    def test_put_overwrites_existing(self):
        cache = TokenCache()
        cache.put("tok1", {"v": 1})
        cache.put("tok1", {"v": 2})
        assert cache.get("tok1") == {"v": 2}
        assert cache.size == 1


class TestTokenCacheTTL:

    def test_expired_entry_returns_none(self):
        cache = TokenCache(ttl=0.05)  # 50ms TTL
        cache.put("tok1", {"data": 1})
        assert cache.get("tok1") is not None
        time.sleep(0.06)
        assert cache.get("tok1") is None

    def test_non_expired_entry_returned(self):
        cache = TokenCache(ttl=10.0)
        cache.put("tok1", {"data": 1})
        assert cache.get("tok1") is not None

    def test_expired_entry_removed_from_cache(self):
        cache = TokenCache(ttl=0.05)
        cache.put("tok1", {"data": 1})
        time.sleep(0.06)
        cache.get("tok1")  # triggers removal
        assert cache.size == 0


class TestTokenCacheLRU:

    def test_eviction_at_capacity(self):
        cache = TokenCache(max_size=3, ttl=60)
        cache.put("tok1", {"data": 1})
        cache.put("tok2", {"data": 2})
        cache.put("tok3", {"data": 3})
        cache.put("tok4", {"data": 4})  # should evict tok1

        assert cache.get("tok1") is None
        assert cache.get("tok2") is not None
        assert cache.get("tok4") is not None
        assert cache.size == 3

    def test_lru_access_updates_order(self):
        cache = TokenCache(max_size=3, ttl=60)
        cache.put("tok1", {"data": 1})
        cache.put("tok2", {"data": 2})
        cache.put("tok3", {"data": 3})

        # Access tok1 to make it recently used
        cache.get("tok1")

        # Add tok4 — should evict tok2 (least recently used), not tok1
        cache.put("tok4", {"data": 4})

        assert cache.get("tok1") is not None  # was accessed, still alive
        assert cache.get("tok2") is None  # evicted
        assert cache.get("tok3") is not None
        assert cache.get("tok4") is not None


class TestTokenCacheThreadSafety:

    def test_concurrent_puts(self):
        cache = TokenCache(max_size=200, ttl=60)
        errors = []

        def writer(start):
            try:
                for i in range(50):
                    cache.put(f"tok-{start}-{i}", {"v": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cache.size == 200

    def test_concurrent_reads_and_writes(self):
        cache = TokenCache(max_size=100, ttl=60)
        for i in range(50):
            cache.put(f"tok-{i}", {"v": i})

        errors = []

        def reader():
            try:
                for i in range(50):
                    cache.get(f"tok-{i}")
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(50, 100):
                    cache.put(f"tok-{i}", {"v": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads += [threading.Thread(target=writer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
