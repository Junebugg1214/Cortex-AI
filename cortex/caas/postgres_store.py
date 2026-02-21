"""
PostgreSQL storage backends for CaaS.

Thread-safe via a shared connection protected by a Python threading.Lock.
All tables created with CREATE TABLE IF NOT EXISTS — no migration runner needed.

Requires ``psycopg`` (v3).  Import is lazy so the rest of Cortex works
without the dependency installed.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from cortex.caas.storage import (
    AbstractAuditLog,
    AbstractGrantStore,
    AbstractPolicyStore,
    AbstractWebhookStore,
)
from cortex.upai.disclosure import DisclosurePolicy
from cortex.upai.webhooks import WebhookRegistration

# ---------------------------------------------------------------------------
# Shared connection base
# ---------------------------------------------------------------------------

class _PostgresBase:
    """Provides a shared psycopg connection with Python-level locking."""

    def __init__(self, conninfo: str) -> None:
        import psycopg

        self._conninfo = conninfo
        self._lock = threading.Lock()
        self._conn = psycopg.connect(conninfo, autocommit=True)
        self._create_tables()

    def _create_tables(self) -> None:
        """Override in subclass to run CREATE TABLE IF NOT EXISTS."""

    def close(self) -> None:
        """Close the connection (for testing)."""
        self._conn.close()


# ---------------------------------------------------------------------------
# PostgresGrantStore
# ---------------------------------------------------------------------------

class PostgresGrantStore(_PostgresBase, AbstractGrantStore):

    def __init__(self, conninfo: str, encryptor=None) -> None:
        self._encryptor = encryptor
        super().__init__(conninfo)

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS grants (
                grant_id   TEXT PRIMARY KEY,
                token_str  TEXT NOT NULL,
                token_data TEXT NOT NULL,
                audience   TEXT NOT NULL DEFAULT '',
                policy     TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                revoked    BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)

    def add(self, grant_id: str, token_str: str, token_data: dict) -> None:
        stored_token = token_str
        if self._encryptor is not None:
            stored_token = self._encryptor.encrypt(token_str)
        with self._lock:
            self._conn.execute(
                "INSERT INTO grants (grant_id, token_str, token_data, audience, policy, created_at, revoked) "
                "VALUES (%s, %s, %s, %s, %s, %s, FALSE) "
                "ON CONFLICT (grant_id) DO UPDATE SET "
                "token_str=EXCLUDED.token_str, token_data=EXCLUDED.token_data, "
                "audience=EXCLUDED.audience, policy=EXCLUDED.policy, "
                "created_at=EXCLUDED.created_at, revoked=EXCLUDED.revoked",
                (
                    grant_id,
                    stored_token,
                    json.dumps(token_data),
                    token_data.get("audience", ""),
                    token_data.get("policy", ""),
                    token_data.get("issued_at", ""),
                ),
            )

    def get(self, grant_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT grant_id, token_str, token_data, created_at, revoked "
                "FROM grants WHERE grant_id = %s",
                (grant_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        token_str = row[1]
        if self._encryptor is not None and self._encryptor.is_encrypted(token_str):
            token_str = self._encryptor.decrypt(token_str)
        return {
            "token_str": token_str,
            "token_data": json.loads(row[2]),
            "created_at": row[3],
            "revoked": bool(row[4]),
        }

    def list_all(self) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT grant_id, token_data, created_at, revoked "
                "FROM grants ORDER BY created_at"
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            token_data = json.loads(row[1])
            result.append({
                "grant_id": row[0],
                "audience": token_data.get("audience", ""),
                "policy": token_data.get("policy", ""),
                "created_at": row[2],
                "revoked": bool(row[3]),
            })
        return result

    def revoke(self, grant_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE grants SET revoked = TRUE WHERE grant_id = %s",
                (grant_id,),
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# PostgresWebhookStore
# ---------------------------------------------------------------------------

class PostgresWebhookStore(_PostgresBase, AbstractWebhookStore):

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                webhook_id TEXT PRIMARY KEY,
                url        TEXT NOT NULL,
                events     TEXT NOT NULL,
                secret     TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                active     BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)

    def add(self, registration: WebhookRegistration) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO webhooks (webhook_id, url, events, secret, created_at, active) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (webhook_id) DO UPDATE SET "
                "url=EXCLUDED.url, events=EXCLUDED.events, secret=EXCLUDED.secret, "
                "created_at=EXCLUDED.created_at, active=EXCLUDED.active",
                (
                    registration.webhook_id,
                    registration.url,
                    json.dumps(registration.events),
                    registration.secret,
                    registration.created_at,
                    registration.active,
                ),
            )

    def get(self, webhook_id: str) -> WebhookRegistration | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT webhook_id, url, events, secret, created_at, active "
                "FROM webhooks WHERE webhook_id = %s",
                (webhook_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return WebhookRegistration(
            webhook_id=row[0],
            url=row[1],
            events=json.loads(row[2]),
            secret=row[3],
            created_at=row[4],
            active=bool(row[5]),
        )

    def list_all(self) -> list[WebhookRegistration]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT webhook_id, url, events, secret, created_at, active "
                "FROM webhooks ORDER BY created_at"
            )
            rows = cur.fetchall()
        return [
            WebhookRegistration(
                webhook_id=row[0],
                url=row[1],
                events=json.loads(row[2]),
                secret=row[3],
                created_at=row[4],
                active=bool(row[5]),
            )
            for row in rows
        ]

    def delete(self, webhook_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM webhooks WHERE webhook_id = %s", (webhook_id,)
            )
            return cur.rowcount > 0

    def get_for_event(self, event: str) -> list[WebhookRegistration]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT webhook_id, url, events, secret, created_at, active "
                "FROM webhooks WHERE active = TRUE"
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            events = json.loads(row[2])
            if event in events:
                result.append(WebhookRegistration(
                    webhook_id=row[0],
                    url=row[1],
                    events=events,
                    secret=row[3],
                    created_at=row[4],
                    active=True,
                ))
        return result


# ---------------------------------------------------------------------------
# PostgresAuditLog
# ---------------------------------------------------------------------------

class PostgresAuditLog(_PostgresBase, AbstractAuditLog):

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         SERIAL PRIMARY KEY,
                timestamp  TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details    TEXT NOT NULL DEFAULT '{}'
            )
        """)

    def log(self, event_type: str, details: dict | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (timestamp, event_type, details) VALUES (%s, %s, %s)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    event_type,
                    json.dumps(details or {}),
                ),
            )

    def query(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        with self._lock:
            if event_type:
                cur = self._conn.execute(
                    "SELECT id, timestamp, event_type, details "
                    "FROM audit_log WHERE event_type = %s ORDER BY id DESC LIMIT %s",
                    (event_type, limit),
                )
            else:
                cur = self._conn.execute(
                    "SELECT id, timestamp, event_type, details "
                    "FROM audit_log ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "event_type": row[2],
                "details": json.loads(row[3]),
            }
            for row in rows
        ]


# ---------------------------------------------------------------------------
# PostgresDeliveryLog
# ---------------------------------------------------------------------------

class PostgresDeliveryLog(_PostgresBase):
    """Webhook delivery attempt log backed by PostgreSQL."""

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                delivery_id  TEXT PRIMARY KEY,
                webhook_id   TEXT NOT NULL,
                event        TEXT NOT NULL,
                status_code  INTEGER NOT NULL DEFAULT 0,
                success      BOOLEAN NOT NULL DEFAULT FALSE,
                error        TEXT NOT NULL DEFAULT '',
                attempt      INTEGER NOT NULL DEFAULT 1,
                delivered_at TEXT NOT NULL DEFAULT ''
            )
        """)

    def record(
        self,
        delivery_id: str,
        webhook_id: str,
        event: str,
        status_code: int,
        success: bool,
        error: str = "",
        attempt: int = 1,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO webhook_deliveries "
                "(delivery_id, webhook_id, event, status_code, success, error, attempt, delivered_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    delivery_id,
                    webhook_id,
                    event,
                    status_code,
                    success,
                    error,
                    attempt,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def query(self, webhook_id: str | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            if webhook_id:
                cur = self._conn.execute(
                    "SELECT delivery_id, webhook_id, event, status_code, success, "
                    "error, attempt, delivered_at "
                    "FROM webhook_deliveries WHERE webhook_id = %s "
                    "ORDER BY delivered_at DESC LIMIT %s",
                    (webhook_id, limit),
                )
            else:
                cur = self._conn.execute(
                    "SELECT delivery_id, webhook_id, event, status_code, success, "
                    "error, attempt, delivered_at "
                    "FROM webhook_deliveries ORDER BY delivered_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
        return [
            {
                "delivery_id": row[0],
                "webhook_id": row[1],
                "event": row[2],
                "status_code": row[3],
                "success": bool(row[4]),
                "error": row[5],
                "attempt": row[6],
                "delivered_at": row[7],
            }
            for row in rows
        ]


# ---------------------------------------------------------------------------
# PostgresPolicyStore
# ---------------------------------------------------------------------------

class PostgresPolicyStore(_PostgresBase, AbstractPolicyStore):

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS policies (
                name              TEXT PRIMARY KEY,
                include_tags      TEXT NOT NULL DEFAULT '[]',
                exclude_tags      TEXT NOT NULL DEFAULT '[]',
                min_confidence    REAL NOT NULL DEFAULT 0.0,
                redact_properties TEXT NOT NULL DEFAULT '[]',
                max_nodes         INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT NOT NULL DEFAULT ''
            )
        """)

    def add(self, policy: DisclosurePolicy) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO policies "
                "(name, include_tags, exclude_tags, min_confidence, redact_properties, max_nodes, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (name) DO UPDATE SET "
                "include_tags=EXCLUDED.include_tags, exclude_tags=EXCLUDED.exclude_tags, "
                "min_confidence=EXCLUDED.min_confidence, redact_properties=EXCLUDED.redact_properties, "
                "max_nodes=EXCLUDED.max_nodes, created_at=EXCLUDED.created_at",
                (
                    policy.name,
                    json.dumps(policy.include_tags),
                    json.dumps(policy.exclude_tags),
                    policy.min_confidence,
                    json.dumps(policy.redact_properties),
                    policy.max_nodes,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get(self, name: str) -> DisclosurePolicy | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT name, include_tags, exclude_tags, min_confidence, "
                "redact_properties, max_nodes "
                "FROM policies WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_policy(row)

    def list_all(self) -> list[DisclosurePolicy]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT name, include_tags, exclude_tags, min_confidence, "
                "redact_properties, max_nodes "
                "FROM policies ORDER BY name"
            )
            rows = cur.fetchall()
        return [self._row_to_policy(row) for row in rows]

    def update(self, name: str, policy: DisclosurePolicy) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT name FROM policies WHERE name = %s", (name,)
            )
            if cur.fetchone() is None:
                return False
            if policy.name != name:
                self._conn.execute("DELETE FROM policies WHERE name = %s", (name,))
            self._conn.execute(
                "INSERT INTO policies "
                "(name, include_tags, exclude_tags, min_confidence, redact_properties, max_nodes, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (name) DO UPDATE SET "
                "include_tags=EXCLUDED.include_tags, exclude_tags=EXCLUDED.exclude_tags, "
                "min_confidence=EXCLUDED.min_confidence, redact_properties=EXCLUDED.redact_properties, "
                "max_nodes=EXCLUDED.max_nodes, created_at=EXCLUDED.created_at",
                (
                    policy.name,
                    json.dumps(policy.include_tags),
                    json.dumps(policy.exclude_tags),
                    policy.min_confidence,
                    json.dumps(policy.redact_properties),
                    policy.max_nodes,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return True

    def delete(self, name: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM policies WHERE name = %s", (name,)
            )
            return cur.rowcount > 0

    @staticmethod
    def _row_to_policy(row: tuple) -> DisclosurePolicy:
        return DisclosurePolicy(
            name=row[0],
            include_tags=json.loads(row[1]),
            exclude_tags=json.loads(row[2]),
            min_confidence=row[3],
            redact_properties=json.loads(row[4]),
            max_nodes=row[5],
        )
