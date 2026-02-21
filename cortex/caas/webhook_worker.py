"""
Background webhook delivery worker.

Daemon thread consuming events from a queue, delivering to all
subscribed webhooks with exponential backoff retry, circuit breakers,
and dead-letter queue for exhausted retries.
"""

from __future__ import annotations

import logging
import queue
import random
import threading
import time
import uuid
from typing import TYPE_CHECKING

from cortex.caas.circuit_breaker import CircuitBreaker
from cortex.caas.dead_letter import DeadLetterQueue
from cortex.upai.webhooks import deliver_webhook

_log = logging.getLogger("caas.webhooks")

if TYPE_CHECKING:
    from cortex.caas.sqlite_store import SqliteDeliveryLog
    from cortex.caas.storage import AbstractWebhookStore


def _jitter(base_delay: float, attempt: int, max_delay: float = 300.0) -> float:
    """Calculate backoff delay with jitter. Capped at max_delay."""
    delay = base_delay ** attempt
    jittered = delay * (0.5 + random.random())  # 50%-150% of base delay
    return min(jittered, max_delay)


class WebhookWorker:
    """Background webhook delivery worker with retry, circuit breaker, and dead-letter."""

    def __init__(
        self,
        webhook_store: AbstractWebhookStore,
        delivery_log: SqliteDeliveryLog | None = None,
        max_retries: int = 3,
        backoff_base: float = 5.0,
        dead_letter_queue: DeadLetterQueue | None = None,
        circuit_failure_threshold: int = 5,
        circuit_cooldown: float = 60.0,
    ) -> None:
        self._webhook_store = webhook_store
        self._delivery_log = delivery_log
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False

        # Dead-letter queue
        self._dead_letter = dead_letter_queue or DeadLetterQueue()

        # Per-webhook circuit breakers
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._cb_lock = threading.Lock()
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_cooldown = circuit_cooldown

    @property
    def dead_letter_queue(self) -> DeadLetterQueue:
        return self._dead_letter

    def _get_circuit(self, webhook_id: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a webhook."""
        with self._cb_lock:
            if webhook_id not in self._circuit_breakers:
                self._circuit_breakers[webhook_id] = CircuitBreaker(
                    failure_threshold=self._circuit_failure_threshold,
                    cooldown_seconds=self._circuit_cooldown,
                )
            return self._circuit_breakers[webhook_id]

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

    def get_health(self, webhook_id: str) -> dict:
        """Get health status for a webhook: circuit state + dead-letter count."""
        cb = self._get_circuit(webhook_id)
        return {
            "webhook_id": webhook_id,
            "circuit": cb.to_dict(),
            "dead_letter_count": self._dead_letter.count(webhook_id),
        }

    def retry_dead_letter(self, webhook_id: str) -> int:
        """Replay all dead-letter events for a webhook. Returns count replayed."""
        entries = self._dead_letter.pop_all_for_webhook(webhook_id)
        for entry in entries:
            self.enqueue(entry.event, entry.data)
        return len(entries)

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
        """Attempt delivery with exponential backoff, circuit breaker, and dead-letter."""
        cb = self._get_circuit(registration.webhook_id)

        # Check circuit breaker
        if not cb.allow_request():
            # Circuit is open — send directly to dead-letter
            _log.warning("Circuit open for %s, routing to dead-letter", registration.webhook_id)
            self._dead_letter.push(
                webhook_id=registration.webhook_id,
                event=event,
                data=data,
                error="circuit_open",
                retry_count=0,
            )
            try:
                from cortex.caas.instrumentation import WEBHOOK_DEAD_LETTERS, WEBHOOK_DELIVERIES
                WEBHOOK_DELIVERIES.inc(webhook_id=registration.webhook_id, status="circuit_open")
                WEBHOOK_DEAD_LETTERS.set(
                    float(self._dead_letter.count(registration.webhook_id)),
                    webhook_id=registration.webhook_id,
                )
            except Exception:
                pass
            return

        last_error = ""
        for attempt in range(1, self._max_retries + 1):
            delivery_id = str(uuid.uuid4())
            success, status_code, headers = deliver_webhook(registration, event, data)

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
                cb.record_success()
                _log.debug("Delivered %s to %s (attempt %d)", event, registration.url, attempt)
                try:
                    from cortex.caas.instrumentation import WEBHOOK_DELIVERIES
                    WEBHOOK_DELIVERIES.inc(webhook_id=registration.webhook_id, status="success")
                except Exception:
                    pass
                return

            last_error = f"HTTP {status_code}"
            _log.warning("Delivery failed %s to %s: HTTP %d (attempt %d/%d)",
                         event, registration.url, status_code, attempt, self._max_retries)

            # 429 Too Many Requests — respect Retry-After, don't trip circuit
            if status_code == 429:
                retry_after = _parse_retry_after(headers)
                if retry_after and attempt < self._max_retries:
                    time.sleep(retry_after)
                    continue

            # Record failure on circuit breaker (not for 429)
            if status_code != 429:
                cb.record_failure()

            # Backoff with jitter
            if attempt < self._max_retries:
                delay = _jitter(self._backoff_base, attempt)
                time.sleep(delay)

        # All retries exhausted — push to dead-letter queue
        _log.error("All retries exhausted for %s to %s, pushing to dead-letter",
                    event, registration.url)
        self._dead_letter.push(
            webhook_id=registration.webhook_id,
            event=event,
            data=data,
            error=last_error,
            retry_count=self._max_retries,
        )
        try:
            from cortex.caas.instrumentation import WEBHOOK_DEAD_LETTERS, WEBHOOK_DELIVERIES
            WEBHOOK_DELIVERIES.inc(webhook_id=registration.webhook_id, status="failure")
            WEBHOOK_DEAD_LETTERS.set(
                float(self._dead_letter.count(registration.webhook_id)),
                webhook_id=registration.webhook_id,
            )
        except Exception:
            pass


def _parse_retry_after(headers: dict[str, str] | None) -> float | None:
    """Parse Retry-After header value (seconds). Returns None if absent/invalid."""
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
        return min(seconds, 300.0)  # cap at 5 minutes
    except (ValueError, TypeError):
        return None
