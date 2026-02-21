"""
CaaS Graceful Shutdown — Coordinated shutdown with signal handlers.

ShutdownCoordinator registers cleanup callbacks and executes them
in reverse registration order when SIGTERM/SIGINT is received.
Thread-safe and idempotent.
"""

from __future__ import annotations

import logging
import signal
import threading
from typing import Callable

_log = logging.getLogger("caas.shutdown")


class ShutdownCoordinator:
    """Coordinates graceful shutdown of CaaS components."""

    def __init__(self) -> None:
        self._callbacks: list[tuple[str, Callable[[], None]]] = []
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._shutting_down = False

    @property
    def is_shutdown(self) -> bool:
        """True if shutdown has been triggered."""
        return self._shutdown_event.is_set()

    def register(self, name: str, callback: Callable[[], None]) -> None:
        """Register a cleanup callback with a descriptive name.

        Callbacks are executed in reverse registration order during shutdown.
        """
        with self._lock:
            self._callbacks.append((name, callback))
            _log.debug("Registered shutdown callback: %s", name)

    def shutdown(self, timeout: float = 10.0) -> None:
        """Execute all registered callbacks in reverse order.

        Each callback gets ``timeout / len(callbacks)`` seconds.
        If a callback raises, it is logged and the next one proceeds.
        Idempotent — calling shutdown() twice is safe.
        """
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            callbacks = list(reversed(self._callbacks))

        if not callbacks:
            self._shutdown_event.set()
            return

        per_cb_timeout = max(timeout / len(callbacks), 1.0)

        _log.info("Shutting down %d components (%.1fs timeout per callback)...",
                   len(callbacks), per_cb_timeout)

        for name, cb in callbacks:
            _log.info("Stopping %s...", name)
            t = threading.Thread(target=cb, daemon=True)
            t.start()
            t.join(timeout=per_cb_timeout)
            if t.is_alive():
                _log.warning("Callback %s did not complete within %.1fs", name, per_cb_timeout)
            else:
                _log.info("Stopped %s", name)

        self._shutdown_event.set()
        _log.info("Shutdown complete")

    def install_signal_handlers(self) -> None:
        """Install SIGTERM and SIGINT handlers (only in main thread).

        Raises RuntimeError if called from a non-main thread.
        """
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Signal handlers can only be installed from the main thread")

        def _handler(signum, frame):
            sig_name = signal.Signals(signum).name
            _log.info("Received %s, initiating shutdown", sig_name)
            self.shutdown()

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """Block until shutdown is triggered. Returns True if shutdown occurred."""
        return self._shutdown_event.wait(timeout=timeout)
