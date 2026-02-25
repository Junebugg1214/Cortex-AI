"""
Sliding-window rate limiter for the CaaS API.

Per-IP tracking with configurable max requests and window.
Thread-safe with Lock. Automatic cleanup of expired windows.

TieredRateLimiter adds per-endpoint rate tiers: auth (10/min),
write (30/min), read (120/min).
"""

from __future__ import annotations

import re
import threading
import time


class RateLimiter:
    """Sliding-window rate limiter."""

    def __init__(self, max_requests: int = 60, window: int = 60) -> None:
        self.max_requests = max_requests
        self.window = window  # seconds
        self._requests: dict[str, list[float]] = {}  # ip → [timestamps]
        self._lock = threading.Lock()

    def allow(self, client_ip: str) -> bool:
        """Return True if the request should be allowed."""
        now = time.monotonic()
        with self._lock:
            timestamps = self._requests.get(client_ip, [])
            # Remove expired entries
            cutoff = now - self.window
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self.max_requests:
                self._requests[client_ip] = timestamps
                return False

            timestamps.append(now)
            self._requests[client_ip] = timestamps
            return True

    def cleanup(self) -> None:
        """Remove all expired entries across all IPs."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            empty_ips = []
            for ip, timestamps in self._requests.items():
                self._requests[ip] = [t for t in timestamps if t > cutoff]
                if not self._requests[ip]:
                    empty_ips.append(ip)
            for ip in empty_ips:
                del self._requests[ip]


# ---------------------------------------------------------------------------
# Tiered rate limiting
# ---------------------------------------------------------------------------

# Auth endpoints — strictest tier
_AUTH_PATHS = {
    "/grants",           # POST /grants
    "/dashboard/auth",   # POST /dashboard/auth
    "/app/auth",         # POST /app/auth
    "/api/token-exchange",  # POST /api/token-exchange
}


def classify_tier(method: str, path: str) -> str:
    """Classify a request into a rate-limit tier: 'auth', 'write', or 'read'."""
    if method == "POST" and path in _AUTH_PATHS:
        return "auth"
    if method in ("POST", "PUT", "DELETE"):
        return "write"
    return "read"


# Default tier limits (requests per 60-second window)
DEFAULT_TIER_LIMITS: dict[str, int] = {
    "auth": 10,
    "write": 30,
    "read": 120,
}


class TieredRateLimiter:
    """Per-endpoint tiered rate limiter wrapping multiple RateLimiter instances."""

    def __init__(
        self,
        tier_limits: dict[str, int] | None = None,
        window: int = 60,
    ) -> None:
        limits = tier_limits or DEFAULT_TIER_LIMITS
        self.window = window
        self._limiters: dict[str, RateLimiter] = {
            tier: RateLimiter(max_requests=max_req, window=window)
            for tier, max_req in limits.items()
        }
        # Fallback for unknown tiers
        self._default = RateLimiter(max_requests=60, window=window)

    def allow(self, client_ip: str, tier: str = "read") -> bool:
        """Return True if the request should be allowed for the given tier."""
        limiter = self._limiters.get(tier, self._default)
        return limiter.allow(client_ip)

    def cleanup(self) -> None:
        """Cleanup all tier limiters."""
        for limiter in self._limiters.values():
            limiter.cleanup()
        self._default.cleanup()
