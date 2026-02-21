"""
SQLite-backed hash-chained audit ledger — persistent, tamper-evident.

Schema::

    CREATE TABLE audit_ledger (
        sequence_id INTEGER PRIMARY KEY,
        timestamp   TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        actor       TEXT NOT NULL DEFAULT 'system',
        request_id  TEXT NOT NULL DEFAULT '',
        details     TEXT NOT NULL DEFAULT '{}',
        prev_hash   TEXT NOT NULL,
        entry_hash  TEXT NOT NULL
    );

Indexes on event_type, actor, timestamp for efficient querying.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from cortex.caas.audit_ledger import (
    GENESIS_HASH,
    AbstractAuditLedger,
    AuditEntry,
    verify_chain,
)


class SqliteAuditLedger(AbstractAuditLedger):
    """Persistent hash-chained audit ledger backed by SQLite."""

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
                CREATE TABLE IF NOT EXISTS audit_ledger (
                    sequence_id INTEGER PRIMARY KEY,
                    timestamp   TEXT NOT NULL,
                    event_type  TEXT NOT NULL,
                    actor       TEXT NOT NULL DEFAULT 'system',
                    request_id  TEXT NOT NULL DEFAULT '',
                    details     TEXT NOT NULL DEFAULT '{}',
                    prev_hash   TEXT NOT NULL,
                    entry_hash  TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_ledger(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_ledger(actor)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_ledger(timestamp)")
            conn.commit()
        finally:
            conn.close()

    def _get_last_hash(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT entry_hash FROM audit_ledger ORDER BY sequence_id DESC LIMIT 1"
        ).fetchone()
        return row["entry_hash"] if row else GENESIS_HASH

    def _get_next_seq(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT MAX(sequence_id) as m FROM audit_ledger"
        ).fetchone()
        return (row["m"] + 1) if row and row["m"] is not None else 0

    def append(self, event_type: str, actor: str = "system",
               request_id: str = "", details: dict | None = None) -> AuditEntry:
        with self._lock:
            conn = self._connect()
            try:
                prev_hash = self._get_last_hash(conn)
                seq = self._get_next_seq(conn)
                entry = AuditEntry(
                    sequence_id=seq,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type=event_type,
                    actor=actor,
                    request_id=request_id,
                    details=details or {},
                    prev_hash=prev_hash,
                )
                entry.entry_hash = entry.compute_hash()
                conn.execute(
                    """INSERT INTO audit_ledger
                       (sequence_id, timestamp, event_type, actor, request_id, details, prev_hash, entry_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entry.sequence_id, entry.timestamp, entry.event_type,
                     entry.actor, entry.request_id,
                     json.dumps(entry.details, sort_keys=True, default=str),
                     entry.prev_hash, entry.entry_hash),
                )
                conn.commit()
                return entry
            finally:
                conn.close()

    def query(self, event_type: str | None = None, actor: str | None = None,
              limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        conn = self._connect()
        try:
            sql = "SELECT * FROM audit_ledger WHERE 1=1"
            params: list = []
            if event_type:
                sql += " AND event_type = ?"
                params.append(event_type)
            if actor:
                sql += " AND actor = ?"
                params.append(actor)
            sql += " ORDER BY sequence_id ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_entry(r) for r in rows]
        finally:
            conn.close()

    def verify(self) -> tuple[bool, int, str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM audit_ledger ORDER BY sequence_id ASC"
            ).fetchall()
            entries = [self._row_to_entry(r) for r in rows]
            return verify_chain(entries)
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) as c FROM audit_ledger").fetchone()
            return row["c"]
        finally:
            conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> AuditEntry:
        details = row["details"]
        if isinstance(details, str):
            details = json.loads(details)
        return AuditEntry(
            sequence_id=row["sequence_id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            actor=row["actor"],
            request_id=row["request_id"],
            details=details,
            prev_hash=row["prev_hash"],
            entry_hash=row["entry_hash"],
        )
