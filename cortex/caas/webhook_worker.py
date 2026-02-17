"""
Background webhook delivery worker.

Daemon thread consuming events from a queue, delivering to all
subscribed webhooks with exponential backoff retry.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import TYPE_CHECKING

from cortex.upai.webhooks import deliver_webhook

if TYPE_CHECKING:
    from cortex.caas.storage import AbstractWebhookStore
    from cortex.caas.sqlite_store import SqliteDeliveryLog


class WebhookWorker:
    """Background webhook delivery worker with retry."""

    def __init__(
        self,
        webhook_store: AbstractWebhookStore,
        delivery_log: SqliteDeliveryLog | None = None,
        max_retries: int = 3,
        backoff_base: float = 5.0,
    ) -> None:
        self._webhook_store = webhook_store
        self._delivery_log = delivery_log
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start the background delivery thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the delivery thread."""
        self._running = False
        self._queue.put(None)  # sentinel to unblock
        if self._thread is not None:
            self._thread.join(timeout=5)

    def enqueue(self, event: str, data: dict) -> None:
        """Enqueue an event for delivery. Non-blocking."""
        self._queue.put((event, data))

    def _run(self) -> None:
        """Main loop: consume events and deliver to matching webhooks."""
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:  # sentinel
                break

            event, data = item
            self._deliver_event(event, data)

    def _deliver_event(self, event: str, data: dict) -> None:
        """Deliver event to all subscribed webhooks with retry."""
        registrations = self._webhook_store.get_for_event(event)
        for reg in registrations:
            self._deliver_with_retry(reg, event, data)

    def _deliver_with_retry(self, registration, event: str, data: dict) -> None:
        """Attempt delivery with exponential backoff."""
        for attempt in range(1, self._max_retries + 1):
            delivery_id = str(uuid.uuid4())
            success, status_code = deliver_webhook(registration, event, data)

            if self._delivery_log is not None:
                self._delivery_log.record(
                    delivery_id=delivery_id,
                    webhook_id=registration.webhook_id,
                    event=event,
                    status_code=status_code,
                    success=success,
                    error="" if success else f"HTTP {status_code}",
                    attempt=attempt,
                )

            if success:
                return

            # Exponential backoff: 5s, 25s
            if attempt < self._max_retries:
                delay = self._backoff_base ** attempt
                time.sleep(delay)
