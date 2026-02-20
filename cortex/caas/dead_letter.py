"""
Dead-letter queue for failed webhook deliveries.

Events that exhaust all retries are stored here for manual replay.
Provides both in-memory and SQLite-backed implementations.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DeadLetterEntry:
    """A failed webhook delivery stored for replay."""
    id: str
    webhook_id: str
    event: str
    data: dict
    failed_at: str
    last_error: str
    retry_count: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "webhook_id": self.webhook_id,
            "event": self.event,
            "data": self.data,
            "failed_at": self.failed_at,
            "last_error": self.last_error,
            "retry_count": self.retry_count,
        }


class DeadLetterQueue:
    """In-memory dead-letter queue."""

    def __init__(self) -> None:
        self._entries: list[DeadLetterEntry] = []
        self._lock = threading.Lock()

    def push(self, webhook_id: str, event: str, data: dict, error: str,
             retry_count: int = 0) -> DeadLetterEntry:
        """Add a failed delivery to the dead-letter queue."""
        entry = DeadLetterEntry(
            id=str(uuid.uuid4()),
            webhook_id=webhook_id,
            event=event,
            data=data,
            failed_at=datetime.now(timezone.utc).isoformat(),
            last_error=error,
            retry_count=retry_count,
        )
        with self._lock:
            self._entries.append(entry)
        return entry

    def list_for_webhook(self, webhook_id: str) -> list[DeadLetterEntry]:
        """List dead-letter entries for a specific webhook."""
        with self._lock:
            return [e for e in self._entries if e.webhook_id == webhook_id]

    def pop(self, entry_id: str) -> DeadLetterEntry | None:
        """Remove and return a dead-letter entry by ID."""
        with self._lock:
            for i, entry in enumerate(self._entries):
                if entry.id == entry_id:
                    return self._entries.pop(i)
        return None

    def count(self, webhook_id: str | None = None) -> int:
        """Count dead-letter entries, optionally filtered by webhook_id."""
        with self._lock:
            if webhook_id is None:
                return len(self._entries)
            return sum(1 for e in self._entries if e.webhook_id == webhook_id)

    def pop_all_for_webhook(self, webhook_id: str) -> list[DeadLetterEntry]:
        """Remove and return all dead-letter entries for a webhook."""
        with self._lock:
            kept = []
            popped = []
            for entry in self._entries:
                if entry.webhook_id == webhook_id:
                    popped.append(entry)
                else:
                    kept.append(entry)
            self._entries = kept
            return popped


class SqliteDeadLetterQueue:
    """SQLite-backed dead-letter queue for persistence across restarts."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letters (
                    id TEXT PRIMARY KEY,
                    webhook_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    failed_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dl_webhook ON dead_letters(webhook_id)")
            conn.commit()
        finally:
            conn.close()

    def push(self, webhook_id: str, event: str, data: dict, error: str,
             retry_count: int = 0) -> DeadLetterEntry:
        entry = DeadLetterEntry(
            id=str(uuid.uuid4()),
            webhook_id=webhook_id,
            event=event,
            data=data,
            failed_at=datetime.now(timezone.utc).isoformat(),
            last_error=error,
            retry_count=retry_count,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO dead_letters (id, webhook_id, event, data, failed_at, last_error, retry_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (entry.id, entry.webhook_id, entry.event,
                     json.dumps(entry.data, default=str),
                     entry.failed_at, entry.last_error, entry.retry_count),
                )
                conn.commit()
            finally:
                conn.close()
        return entry

    def list_for_webhook(self, webhook_id: str) -> list[DeadLetterEntry]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM dead_letters WHERE webhook_id = ? ORDER BY failed_at ASC",
                (webhook_id,)
            ).fetchall()
            return [self._row_to_entry(r) for r in rows]
        finally:
            conn.close()

    def pop(self, entry_id: str) -> DeadLetterEntry | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM dead_letters WHERE id = ?", (entry_id,)).fetchone()
                if row is None:
                    return None
                entry = self._row_to_entry(row)
                conn.execute("DELETE FROM dead_letters WHERE id = ?", (entry_id,))
                conn.commit()
                return entry
            finally:
                conn.close()

    def count(self, webhook_id: str | None = None) -> int:
        conn = self._connect()
        try:
            if webhook_id is None:
                row = conn.execute("SELECT COUNT(*) as c FROM dead_letters").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM dead_letters WHERE webhook_id = ?",
                    (webhook_id,)
                ).fetchone()
            return row["c"]
        finally:
            conn.close()

    def pop_all_for_webhook(self, webhook_id: str) -> list[DeadLetterEntry]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM dead_letters WHERE webhook_id = ? ORDER BY failed_at ASC",
                    (webhook_id,)
                ).fetchall()
                entries = [self._row_to_entry(r) for r in rows]
                conn.execute("DELETE FROM dead_letters WHERE webhook_id = ?", (webhook_id,))
                conn.commit()
                return entries
            finally:
                conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> DeadLetterEntry:
        data = row["data"]
        if isinstance(data, str):
            data = json.loads(data)
        return DeadLetterEntry(
            id=row["id"],
            webhook_id=row["webhook_id"],
            event=row["event"],
            data=data,
            failed_at=row["failed_at"],
            last_error=row["last_error"],
            retry_count=row["retry_count"],
        )
