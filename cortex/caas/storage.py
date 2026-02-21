"""
Abstract storage interfaces and JSON implementations for CaaS.

Three storage abstractions mirror CaaS server needs:
- AbstractGrantStore — grant token CRUD
- AbstractWebhookStore — webhook registration CRUD
- AbstractAuditLog — append-only event log

JSON/in-memory implementations are the default (backward-compatible).
SQLite implementations live in sqlite_store.py.
"""

from __future__ import annotations

import abc
import threading
from datetime import datetime, timezone

from cortex.upai.disclosure import DisclosurePolicy
from cortex.upai.webhooks import WebhookRegistration

# ---------------------------------------------------------------------------
# Abstract interfaces
# ---------------------------------------------------------------------------

class AbstractGrantStore(abc.ABC):
    """Thread-safe grant token store interface."""

    @abc.abstractmethod
    def add(self, grant_id: str, token_str: str, token_data: dict) -> None: ...

    @abc.abstractmethod
    def get(self, grant_id: str) -> dict | None: ...

    @abc.abstractmethod
    def list_all(self) -> list[dict]: ...

    @abc.abstractmethod
    def revoke(self, grant_id: str) -> bool: ...


class AbstractWebhookStore(abc.ABC):
    """Thread-safe webhook registration store interface."""

    @abc.abstractmethod
    def add(self, registration: WebhookRegistration) -> None: ...

    @abc.abstractmethod
    def get(self, webhook_id: str) -> WebhookRegistration | None: ...

    @abc.abstractmethod
    def list_all(self) -> list[WebhookRegistration]: ...

    @abc.abstractmethod
    def delete(self, webhook_id: str) -> bool: ...

    @abc.abstractmethod
    def get_for_event(self, event: str) -> list[WebhookRegistration]: ...


class AbstractPolicyStore(abc.ABC):
    """Thread-safe custom policy store interface."""

    @abc.abstractmethod
    def add(self, policy: DisclosurePolicy) -> None: ...

    @abc.abstractmethod
    def get(self, name: str) -> DisclosurePolicy | None: ...

    @abc.abstractmethod
    def list_all(self) -> list[DisclosurePolicy]: ...

    @abc.abstractmethod
    def update(self, name: str, policy: DisclosurePolicy) -> bool: ...

    @abc.abstractmethod
    def delete(self, name: str) -> bool: ...


class AbstractAuditLog(abc.ABC):
    """Append-only audit event log interface."""

    @abc.abstractmethod
    def log(self, event_type: str, details: dict | None = None) -> None: ...

    @abc.abstractmethod
    def query(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]: ...


# ---------------------------------------------------------------------------
# JSON / in-memory implementations
# ---------------------------------------------------------------------------

class JsonWebhookStore(AbstractWebhookStore):
    """Thread-safe in-memory webhook store (replaces bare dict)."""

    def __init__(self) -> None:
        self._webhooks: dict[str, WebhookRegistration] = {}
        self._lock = threading.Lock()

    def add(self, registration: WebhookRegistration) -> None:
        with self._lock:
            self._webhooks[registration.webhook_id] = registration

    def get(self, webhook_id: str) -> WebhookRegistration | None:
        with self._lock:
            return self._webhooks.get(webhook_id)

    def list_all(self) -> list[WebhookRegistration]:
        with self._lock:
            return list(self._webhooks.values())

    def delete(self, webhook_id: str) -> bool:
        with self._lock:
            if webhook_id in self._webhooks:
                del self._webhooks[webhook_id]
                return True
            return False

    def get_for_event(self, event: str) -> list[WebhookRegistration]:
        with self._lock:
            return [
                reg for reg in self._webhooks.values()
                if reg.active and event in reg.events
            ]


class InMemoryAuditLog(AbstractAuditLog):
    """Thread-safe in-memory audit log (non-persistent)."""

    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._lock = threading.Lock()

    def log(self, event_type: str, details: dict | None = None) -> None:
        with self._lock:
            self._entries.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "details": details or {},
            })

    def query(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        with self._lock:
            entries = self._entries
            if event_type:
                entries = [e for e in entries if e["event_type"] == event_type]
            return list(reversed(entries[:limit]))


class JsonPolicyStore(AbstractPolicyStore):
    """Thread-safe in-memory policy store."""

    def __init__(self) -> None:
        self._policies: dict[str, DisclosurePolicy] = {}
        self._lock = threading.Lock()

    def add(self, policy: DisclosurePolicy) -> None:
        with self._lock:
            self._policies[policy.name] = policy

    def get(self, name: str) -> DisclosurePolicy | None:
        with self._lock:
            return self._policies.get(name)

    def list_all(self) -> list[DisclosurePolicy]:
        with self._lock:
            return list(self._policies.values())

    def update(self, name: str, policy: DisclosurePolicy) -> bool:
        with self._lock:
            if name not in self._policies:
                return False
            if policy.name != name:
                del self._policies[name]
            self._policies[policy.name] = policy
            return True

    def delete(self, name: str) -> bool:
        with self._lock:
            if name not in self._policies:
                return False
            del self._policies[name]
            return True
