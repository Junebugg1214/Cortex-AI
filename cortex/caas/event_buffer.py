"""
SSE Event Buffer — Ring buffer for event replay on reconnect.

Uses collections.deque(maxlen=N) for O(1) append with automatic eviction.
Events are assigned monotonically increasing IDs for Last-Event-ID support.
Optional TTL-based cleanup discards events older than a threshold.
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass


@dataclass
class BufferedEvent:
    """A buffered SSE event with a monotonic ID."""
    event_id: int
    event_type: str
    data: str             # JSON-encoded payload
    timestamp: float      # time.monotonic()


class EventBuffer:
    """Ring buffer for SSE event replay."""

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 3600.0) -> None:
        self._buffer: collections.deque[BufferedEvent] = collections.deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._next_id: int = 1
        self._ttl = ttl_seconds

    @property
    def max_size(self) -> int:
        return self._buffer.maxlen  # type: ignore[return-value]

    def append(self, event_type: str, data: str) -> int:
        """Add an event to the buffer. Returns the monotonic event ID."""
        with self._lock:
            event_id = self._next_id
            self._next_id += 1
            event = BufferedEvent(
                event_id=event_id,
                event_type=event_type,
                data=data,
                timestamp=time.monotonic(),
            )
            self._buffer.append(event)
            return event_id

    def since(self, event_id: int) -> list[BufferedEvent]:
        """Return all events with ID > event_id. Thread-safe."""
        with self._lock:
            self._cleanup_expired()
            return [e for e in self._buffer if e.event_id > event_id]

    def latest_id(self) -> int:
        """Return the most recent event ID, or 0 if buffer is empty."""
        with self._lock:
            if self._buffer:
                return self._buffer[-1].event_id
            return 0

    def count(self) -> int:
        """Number of events in the buffer."""
        with self._lock:
            return len(self._buffer)

    def _cleanup_expired(self) -> None:
        """Remove events older than TTL. Called while lock is held."""
        if self._ttl <= 0:
            return
        cutoff = time.monotonic() - self._ttl
        while self._buffer and self._buffer[0].timestamp < cutoff:
            self._buffer.popleft()
