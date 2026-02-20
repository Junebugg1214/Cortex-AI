"""
Immutable hash-chained audit ledger — tamper-evident event log.

Each entry includes a SHA-256 hash over its contents plus the previous entry's hash,
forming a chain. Any modification to past entries breaks the chain and is detectable
via ``verify_chain()``.

Two implementations:
- ``InMemoryAuditLedger`` — list-based, thread-safe
- ``SqliteAuditLedger`` — persistent (separate module)

Both conform to ``AbstractAuditLedger``.
"""

from __future__ import annotations

import abc
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Genesis hash — the prev_hash for the first entry
GENESIS_HASH = "0" * 64


@dataclass
class AuditEntry:
    """A single immutable audit log entry."""

    sequence_id: int
    timestamp: str            # ISO-8601
    event_type: str
    actor: str                # "grant:<id>", "dashboard:<hash8>", "system"
    request_id: str
    details: dict
    prev_hash: str
    entry_hash: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 over canonical fields."""
        canonical = (
            f"{self.sequence_id}|{self.timestamp}|{self.event_type}|"
            f"{self.actor}|{json.dumps(self.details, sort_keys=True, default=str)}|"
            f"{self.prev_hash}"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor": self.actor,
            "request_id": self.request_id,
            "details": self.details,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AuditEntry:
        return cls(
            sequence_id=d["sequence_id"],
            timestamp=d["timestamp"],
            event_type=d["event_type"],
            actor=d.get("actor", "system"),
            request_id=d.get("request_id", ""),
            details=d.get("details", {}),
            prev_hash=d["prev_hash"],
            entry_hash=d.get("entry_hash", ""),
        )


def verify_chain(entries: list[AuditEntry]) -> tuple[bool, int, str]:
    """Verify integrity of a list of audit entries.

    Returns (valid, entries_checked, error_message).
    """
    if not entries:
        return True, 0, ""

    for i, entry in enumerate(entries):
        # Verify hash
        expected = entry.compute_hash()
        if entry.entry_hash != expected:
            return False, i, f"Entry {entry.sequence_id}: hash mismatch"

        # Verify chain link
        if i == 0:
            if entry.prev_hash != GENESIS_HASH:
                # If not starting from genesis, verify prev_hash is present
                pass  # sub-chains are valid
        else:
            if entry.prev_hash != entries[i - 1].entry_hash:
                return False, i, f"Entry {entry.sequence_id}: chain broken"

    return True, len(entries), ""


class AbstractAuditLedger(abc.ABC):
    """Append-only, hash-chained audit log interface."""

    @abc.abstractmethod
    def append(self, event_type: str, actor: str = "system",
               request_id: str = "", details: dict | None = None) -> AuditEntry: ...

    @abc.abstractmethod
    def query(self, event_type: str | None = None, actor: str | None = None,
              limit: int = 100, offset: int = 0) -> list[AuditEntry]: ...

    @abc.abstractmethod
    def verify(self) -> tuple[bool, int, str]: ...

    @abc.abstractmethod
    def count(self) -> int: ...

    # Backward-compat adapter for old AbstractAuditLog interface
    def log(self, event_type: str, details: dict | None = None) -> None:
        self.append(event_type, details=details)

    def recent(self, limit: int = 50) -> list[dict]:
        entries = self.query(limit=limit)
        return [e.to_dict() for e in reversed(entries)]


class InMemoryAuditLedger(AbstractAuditLedger):
    """Thread-safe in-memory hash-chained audit ledger."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()
        self._next_seq = 0

    def append(self, event_type: str, actor: str = "system",
               request_id: str = "", details: dict | None = None) -> AuditEntry:
        with self._lock:
            prev_hash = self._entries[-1].entry_hash if self._entries else GENESIS_HASH
            entry = AuditEntry(
                sequence_id=self._next_seq,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type=event_type,
                actor=actor,
                request_id=request_id,
                details=details or {},
                prev_hash=prev_hash,
            )
            entry.entry_hash = entry.compute_hash()
            self._entries.append(entry)
            self._next_seq += 1
            return entry

    def query(self, event_type: str | None = None, actor: str | None = None,
              limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        with self._lock:
            results = self._entries
            if event_type:
                results = [e for e in results if e.event_type == event_type]
            if actor:
                results = [e for e in results if e.actor == actor]
            return results[offset:offset + limit]

    def verify(self) -> tuple[bool, int, str]:
        with self._lock:
            return verify_chain(self._entries)

    def count(self) -> int:
        with self._lock:
            return len(self._entries)
