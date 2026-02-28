"""
PostgreSQL-backed hash-chained audit ledger — persistent, tamper-evident.

Schema::

    CREATE TABLE audit_ledger (
        sequence_id SERIAL PRIMARY KEY,
        timestamp   TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        actor       TEXT NOT NULL DEFAULT 'system',
        request_id  TEXT NOT NULL DEFAULT '',
        details     TEXT NOT NULL DEFAULT '{}',
        prev_hash   TEXT NOT NULL,
        entry_hash  TEXT NOT NULL
    );

Indexes on event_type, actor, timestamp for efficient querying.

Requires ``psycopg`` (v3).  Import is lazy so the rest of Cortex works
without the dependency installed.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from cortex.caas.audit_ledger import (
    GENESIS_HASH,
    AbstractAuditLedger,
    AuditEntry,
    verify_chain,
)


class PostgresAuditLedger(AbstractAuditLedger):
    """Persistent hash-chained audit ledger backed by PostgreSQL."""

    def __init__(self, conninfo: str) -> None:
        import psycopg

        self._conninfo = conninfo
        self._lock = threading.Lock()
        self._conn = psycopg.connect(conninfo, autocommit=True)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_ledger (
                sequence_id SERIAL PRIMARY KEY,
                timestamp   TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                actor       TEXT NOT NULL DEFAULT 'system',
                request_id  TEXT NOT NULL DEFAULT '',
                details     TEXT NOT NULL DEFAULT '{}',
                prev_hash   TEXT NOT NULL,
                entry_hash  TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pg_audit_event ON audit_ledger(event_type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pg_audit_actor ON audit_ledger(actor)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pg_audit_ts ON audit_ledger(timestamp)"
        )

    def _get_last_hash(self) -> str:
        cur = self._conn.execute(
            "SELECT entry_hash FROM audit_ledger ORDER BY sequence_id DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else GENESIS_HASH

    def _get_next_seq(self) -> int:
        cur = self._conn.execute(
            "SELECT MAX(sequence_id) FROM audit_ledger"
        )
        row = cur.fetchone()
        val = row[0] if row else None
        return (val + 1) if val is not None else 0

    def append(self, event_type: str, actor: str = "system",
               request_id: str = "", details: dict | None = None) -> AuditEntry:
        with self._lock:
            prev_hash = self._get_last_hash()
            seq = self._get_next_seq()
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
            self._conn.execute(
                """INSERT INTO audit_ledger
                   (sequence_id, timestamp, event_type, actor, request_id, details, prev_hash, entry_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (entry.sequence_id, entry.timestamp, entry.event_type,
                 entry.actor, entry.request_id,
                 json.dumps(entry.details, sort_keys=True, default=str),
                 entry.prev_hash, entry.entry_hash),
            )
            return entry

    def query(self, event_type: str | None = None, actor: str | None = None,
              limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        with self._lock:
            sql = "SELECT sequence_id, timestamp, event_type, actor, request_id, details, prev_hash, entry_hash FROM audit_ledger WHERE 1=1"
            params: list = []
            if event_type:
                sql += " AND event_type = %s"
                params.append(event_type)
            if actor:
                sql += " AND actor = %s"
                params.append(actor)
            sql += " ORDER BY sequence_id ASC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_entry(r) for r in rows]

    def verify(self) -> tuple[bool, int, str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT sequence_id, timestamp, event_type, actor, request_id, "
                "details, prev_hash, entry_hash "
                "FROM audit_ledger ORDER BY sequence_id ASC"
            )
            rows = cur.fetchall()
        entries = [self._row_to_entry(r) for r in rows]
        return verify_chain(entries)

    def count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM audit_ledger")
            row = cur.fetchone()
            return row[0]

    def rotate(self, before) -> int:
        """Delete entries older than *before* (datetime). Returns deleted count."""
        cutoff_iso = before.isoformat()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM audit_ledger WHERE timestamp < %s", (cutoff_iso,)
            )
            return cur.rowcount

    def close(self) -> None:
        """Close the connection (for testing)."""
        self._conn.close()

    @staticmethod
    def _row_to_entry(row: tuple) -> AuditEntry:
        details = row[5]
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                details = {}
        return AuditEntry(
            sequence_id=row[0],
            timestamp=row[1],
            event_type=row[2],
            actor=row[3],
            request_id=row[4],
            details=details,
            prev_hash=row[6],
            entry_hash=row[7],
        )
