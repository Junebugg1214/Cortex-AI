"""
Sliding-window rate limiter for the CaaS API.

Per-IP tracking with configurable max requests and window.
Thread-safe with Lock. Automatic cleanup of expired windows.
"""

from __future__ import annotations

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
