"""
Circuit breaker for webhook delivery — prevents cascading failures.

States:
- CLOSED: normal operation, requests flow through
- OPEN: failures exceeded threshold, requests blocked
- HALF_OPEN: cooldown expired, allow one probe request

Thread-safe with threading.Lock().
"""

from __future__ import annotations

import threading
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-webhook circuit breaker."""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._last_success_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._get_state()

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def last_success_time(self) -> float:
        with self._lock:
            return self._last_success_time

    @property
    def last_failure_time(self) -> float:
        with self._lock:
            return self._last_failure_time

    def _get_state(self) -> CircuitState:
        """Get current state, transitioning OPEN → HALF_OPEN if cooldown expired."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._cooldown:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        with self._lock:
            state = self._get_state()
            if state == CircuitState.CLOSED:
                return True
            if state == CircuitState.HALF_OPEN:
                return True  # allow probe
            return False  # OPEN

    def record_success(self) -> None:
        """Record a successful delivery."""
        with self._lock:
            self._failure_count = 0
            self._last_success_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed delivery. Opens circuit if threshold exceeded."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — reopen
                self._state = CircuitState.OPEN
            elif self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Reset the circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def to_dict(self) -> dict:
        """Return circuit breaker status as a dict."""
        with self._lock:
            state = self._get_state()
            return {
                "state": state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self._failure_threshold,
                "cooldown_seconds": self._cooldown,
                "last_success_time": self._last_success_time,
                "last_failure_time": self._last_failure_time,
            }
