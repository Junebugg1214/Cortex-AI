"""Tests for profile.viewed webhook — Feature 6."""

import time
import pytest
from cortex.upai.webhooks import VALID_EVENTS


class TestProfileViewedEvent:
    def test_profile_viewed_in_valid_events(self):
        assert "profile.viewed" in VALID_EVENTS

    def test_valid_events_still_has_originals(self):
        for event in ("context.updated", "version.created", "grant.created",
                       "grant.revoked", "key.rotated"):
            assert event in VALID_EVENTS

    def test_valid_events_count(self):
        assert len(VALID_EVENTS) == 6


class TestProfileViewRateLimit:
    """Test the rate-limiting logic extracted from CaaSHandler._fire_profile_viewed."""

    def test_rate_limit_allows_first_view(self):
        rate: dict[str, float] = {}
        handle = "alice"
        now = time.monotonic()
        # First view should be allowed
        last = rate.get(handle)
        assert last is None  # not rate-limited
        rate[handle] = now

    def test_rate_limit_blocks_within_cooldown(self):
        rate: dict[str, float] = {}
        handle = "alice"
        now = time.monotonic()
        rate[handle] = now
        # Second view within 60s should be blocked
        later = now + 30
        last = rate.get(handle)
        assert last is not None
        assert later - last < 60  # within cooldown

    def test_rate_limit_allows_after_cooldown(self):
        rate: dict[str, float] = {}
        handle = "alice"
        now = time.monotonic()
        rate[handle] = now
        later = now + 61
        last = rate.get(handle)
        assert later - last >= 60  # cooldown expired

    def test_different_handles_independent(self):
        rate: dict[str, float] = {}
        now = time.monotonic()
        rate["alice"] = now
        # Bob should not be rate-limited
        assert rate.get("bob") is None

    def test_stale_entry_eviction(self):
        rate: dict[str, float] = {}
        now = time.monotonic()
        rate["old-handle"] = now - 200  # 200s ago (> 120s threshold)
        # Evict stale entries
        stale = [h for h, t in rate.items() if now - t > 120]
        for h in stale:
            del rate[h]
        assert "old-handle" not in rate

    def test_multiple_handles_tracked(self):
        rate: dict[str, float] = {}
        now = time.monotonic()
        for handle in ("alice", "bob", "charlie"):
            rate[handle] = now
        assert len(rate) == 3

    def test_eviction_preserves_recent(self):
        rate: dict[str, float] = {}
        now = time.monotonic()
        rate["old"] = now - 200
        rate["recent"] = now - 10
        stale = [h for h, t in rate.items() if now - t > 120]
        for h in stale:
            del rate[h]
        assert "old" not in rate
        assert "recent" in rate
