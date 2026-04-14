"""Shared graceful-shutdown helpers for long-running Cortex processes."""

from __future__ import annotations

import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class GracefulShutdown(RuntimeError):
    """Raised when a runtime process should stop cleanly."""


class ShutdownController:
    """Track one runtime process shutdown request."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason = ""

    def request_shutdown(self, reason: str) -> None:
        """Mark the runtime for shutdown and keep the first reason."""
        if not self._event.is_set():
            self.reason = str(reason)
            self._event.set()

    @property
    def stop_requested(self) -> bool:
        """Whether shutdown has been requested."""
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until shutdown is requested or the timeout elapses."""
        return self._event.wait(timeout)


@contextmanager
def install_shutdown_handlers(
    controller: ShutdownController,
    *,
    raise_on_signal: bool = False,
) -> Iterator[None]:
    """Temporarily install SIGINT/SIGTERM handlers for graceful shutdown."""

    previous: dict[int, object] = {}
    installed: list[int] = []

    def _handler(signum: int, _frame: object) -> None:
        signal_name = signal.Signals(signum).name
        controller.request_shutdown(f"Received {signal_name}")
        if raise_on_signal:
            raise GracefulShutdown(controller.reason)

    for name in ("SIGINT", "SIGTERM"):
        if not hasattr(signal, name):
            continue
        signum = getattr(signal, name)
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _handler)
        installed.append(signum)
    try:
        yield
    finally:
        for signum in installed:
            signal.signal(signum, previous[signum])


__all__ = ["GracefulShutdown", "ShutdownController", "install_shutdown_handlers"]
