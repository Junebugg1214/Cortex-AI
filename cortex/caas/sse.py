"""
CaaS Server-Sent Events — Real-time push over plain HTTP/1.1.

SSE uses Content-Type: text/event-stream with chunked responses.
One-directional (server -> client). Clients reconnect via EventSource API.

Wire format:
    event: context.updated
    data: {"nodes_changed": [...]}

    :heartbeat

"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SSESubscriber:
    """A connected SSE client."""

    subscriber_id: str        # uuid4
    wfile: Any                # socket write file object
    events: set[str]          # {"context.updated", "grant.created", ...}
    grant_id: str             # for audit
    connected_at: float       # time.monotonic()
    alive: bool = True


class SSEManager:
    """Manages SSE subscribers and broadcasts events."""

    def __init__(self, heartbeat_interval: float = 30.0) -> None:
        self._subscribers: dict[str, SSESubscriber] = {}
        self._lock = threading.Lock()
        self._heartbeat_interval = heartbeat_interval
        self._running = False
        self._heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the heartbeat thread."""
        if self._running:
            return
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="sse-heartbeat"
        )
        self._heartbeat_thread.start()

    def shutdown(self) -> None:
        """Stop heartbeat and close all connections."""
        self._running = False
        with self._lock:
            for sub in self._subscribers.values():
                sub.alive = False
            self._subscribers.clear()

    def subscribe(
        self,
        wfile: Any,
        events: set[str] | None = None,
        grant_id: str = "",
    ) -> SSESubscriber:
        """Register a new subscriber."""
        sub = SSESubscriber(
            subscriber_id=str(uuid.uuid4()),
            wfile=wfile,
            events=events or set(),
            grant_id=grant_id,
            connected_at=time.monotonic(),
        )
        with self._lock:
            self._subscribers[sub.subscriber_id] = sub
        return sub

    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber."""
        with self._lock:
            sub = self._subscribers.pop(subscriber_id, None)
            if sub:
                sub.alive = False

    def broadcast(self, event_type: str, data: Any) -> int:
        """Send event to all matching subscribers. Returns count of deliveries."""
        payload = json.dumps(data, default=str)
        delivered = 0
        dead: list[str] = []

        with self._lock:
            for sid, sub in self._subscribers.items():
                # Empty events set means subscribe to all
                if sub.events and event_type not in sub.events:
                    continue
                if not self._send(sub, event_type, payload):
                    dead.append(sid)
                else:
                    delivered += 1

            # Clean up dead connections
            for sid in dead:
                removed = self._subscribers.pop(sid, None)
                if removed:
                    removed.alive = False

        return delivered

    def _send(self, subscriber: SSESubscriber, event: str, data: str) -> bool:
        """Write an SSE-formatted message. Returns False if connection is broken."""
        if not subscriber.alive:
            return False
        try:
            message = f"event: {event}\ndata: {data}\n\n"
            subscriber.wfile.write(message.encode("utf-8"))
            subscriber.wfile.flush()
            return True
        except (OSError, BrokenPipeError, ConnectionResetError):
            subscriber.alive = False
            return False

    def _send_comment(self, subscriber: SSESubscriber, comment: str) -> bool:
        """Send an SSE comment (heartbeat). Returns False if broken."""
        if not subscriber.alive:
            return False
        try:
            subscriber.wfile.write(f":{comment}\n\n".encode("utf-8"))
            subscriber.wfile.flush()
            return True
        except (OSError, BrokenPipeError, ConnectionResetError):
            subscriber.alive = False
            return False

    def _heartbeat_loop(self) -> None:
        """Periodically send heartbeat comments to all subscribers."""
        while self._running:
            time.sleep(self._heartbeat_interval)
            if not self._running:
                break

            dead: list[str] = []
            with self._lock:
                for sid, sub in self._subscribers.items():
                    if not self._send_comment(sub, "heartbeat"):
                        dead.append(sid)
                for sid in dead:
                    removed = self._subscribers.pop(sid, None)
                    if removed:
                        removed.alive = False

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        with self._lock:
            return len(self._subscribers)
