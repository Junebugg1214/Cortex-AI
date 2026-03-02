"""
SQLite storage backends for CaaS.

Thread-safe via a shared connection protected by a Python threading.Lock.
Uses WAL journal mode for better concurrent read performance.
All tables created with CREATE TABLE IF NOT EXISTS — no migration runner needed.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from cortex.caas.storage import (
    AbstractAuditLog,
    AbstractConnectorStore,
    AbstractGrantStore,
    AbstractPolicyStore,
    AbstractWebhookStore,
)
from cortex.upai.disclosure import DisclosurePolicy
from cortex.upai.webhooks import WebhookRegistration

# ---------------------------------------------------------------------------
# Shared connection base
# ---------------------------------------------------------------------------

class _SqliteBase:
    """Provides a shared SQLite connection with Python-level locking."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-8000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._run_migrations()

    def _create_tables(self) -> None:
        """Override in subclass to run CREATE TABLE IF NOT EXISTS."""
        pass

    def _run_migrations(self) -> None:
        """Run pending schema migrations after table creation."""
        try:
            from cortex.caas.migrations import MigrationRunner
            runner = MigrationRunner(self._conn)
            runner.migrate()
        except Exception:
            pass  # Don't fail store init if migrations module unavailable

    def close(self) -> None:
        """Close the connection (for testing)."""
        self._conn.close()


# ---------------------------------------------------------------------------
# SqliteGrantStore
# ---------------------------------------------------------------------------

class SqliteGrantStore(_SqliteBase, AbstractGrantStore):

    def __init__(self, db_path: str, encryptor=None) -> None:
        self._encryptor = encryptor
        super().__init__(db_path)

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS grants (
                grant_id   TEXT PRIMARY KEY,
                token_str  TEXT NOT NULL,
                token_data TEXT NOT NULL,
                audience   TEXT NOT NULL DEFAULT '',
                policy     TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                revoked    INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.commit()

    def add(self, grant_id: str, token_str: str, token_data: dict) -> None:
        # Encrypt token_str if encryptor is available
        stored_token = token_str
        if self._encryptor is not None:
            stored_token = self._encryptor.encrypt(token_str)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO grants (grant_id, token_str, token_data, audience, policy, created_at, revoked) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    grant_id,
                    stored_token,
                    json.dumps(token_data),
                    token_data.get("audience", ""),
                    token_data.get("policy", ""),
                    token_data.get("issued_at", ""),
                ),
            )
            self._conn.commit()

    def get(self, grant_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        if row is None:
            return None
        # Decrypt token_str if it's encrypted
        token_str = row["token_str"]
        if self._encryptor is not None and self._encryptor.is_encrypted(token_str):
            token_str = self._encryptor.decrypt(token_str)
        try:
            token_data = json.loads(row["token_data"])
        except (json.JSONDecodeError, TypeError):
            token_data = {}
        return {
            "token_str": token_str,
            "token_data": token_data,
            "created_at": row["created_at"],
            "revoked": bool(row["revoked"]),
        }

    def list_all(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM grants ORDER BY created_at").fetchall()
        result = []
        for row in rows:
            try:
                token_data = json.loads(row["token_data"])
            except (json.JSONDecodeError, TypeError):
                token_data = {}
            result.append({
                "grant_id": row["grant_id"],
                "audience": token_data.get("audience", ""),
                "policy": token_data.get("policy", ""),
                "created_at": row["created_at"],
                "revoked": bool(row["revoked"]),
            })
        return result

    def revoke(self, grant_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE grants SET revoked = 1 WHERE grant_id = ?", (grant_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# SqliteWebhookStore
# ---------------------------------------------------------------------------

class SqliteWebhookStore(_SqliteBase, AbstractWebhookStore):

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                webhook_id TEXT PRIMARY KEY,
                url        TEXT NOT NULL,
                events     TEXT NOT NULL,
                secret     TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                active     INTEGER NOT NULL DEFAULT 1
            )
        """)
        self._conn.commit()

    def add(self, registration: WebhookRegistration) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO webhooks (webhook_id, url, events, secret, created_at, active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    registration.webhook_id,
                    registration.url,
                    json.dumps(registration.events),
                    registration.secret,
                    registration.created_at,
                    1 if registration.active else 0,
                ),
            )
            self._conn.commit()

    def get(self, webhook_id: str) -> WebhookRegistration | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM webhooks WHERE webhook_id = ?", (webhook_id,)
            ).fetchone()
        if row is None:
            return None
        return WebhookRegistration(
            webhook_id=row["webhook_id"],
            url=row["url"],
            events=json.loads(row["events"]),
            secret=row["secret"],
            created_at=row["created_at"],
            active=bool(row["active"]),
        )

    def list_all(self) -> list[WebhookRegistration]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM webhooks ORDER BY created_at").fetchall()
        return [
            WebhookRegistration(
                webhook_id=row["webhook_id"],
                url=row["url"],
                events=json.loads(row["events"]),
                secret=row["secret"],
                created_at=row["created_at"],
                active=bool(row["active"]),
            )
            for row in rows
        ]

    def delete(self, webhook_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM webhooks WHERE webhook_id = ?", (webhook_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_for_event(self, event: str) -> list[WebhookRegistration]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM webhooks WHERE active = 1"
            ).fetchall()
        result = []
        for row in rows:
            events = json.loads(row["events"])
            if event in events:
                result.append(WebhookRegistration(
                    webhook_id=row["webhook_id"],
                    url=row["url"],
                    events=events,
                    secret=row["secret"],
                    created_at=row["created_at"],
                    active=True,
                ))
        return result


# ---------------------------------------------------------------------------
# SqliteAuditLog
# ---------------------------------------------------------------------------

class SqliteAuditLog(_SqliteBase, AbstractAuditLog):

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details    TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self._conn.commit()

    def log(self, event_type: str, details: dict | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (timestamp, event_type, details) VALUES (?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    event_type,
                    json.dumps(details or {}),
                ),
            )
            self._conn.commit()

    def query(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        with self._lock:
            if event_type:
                rows = self._conn.execute(
                    "SELECT * FROM audit_log WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                    (event_type, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "details": json.loads(row["details"]),
            }
            for row in rows
        ]


# ---------------------------------------------------------------------------
# SqliteDeliveryLog
# ---------------------------------------------------------------------------

class SqliteDeliveryLog(_SqliteBase):
    """Webhook delivery attempt log."""

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                delivery_id TEXT PRIMARY KEY,
                webhook_id  TEXT NOT NULL,
                event       TEXT NOT NULL,
                status_code INTEGER NOT NULL DEFAULT 0,
                success     INTEGER NOT NULL DEFAULT 0,
                error       TEXT NOT NULL DEFAULT '',
                attempt     INTEGER NOT NULL DEFAULT 1,
                delivered_at TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

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
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    delivery_id,
                    webhook_id,
                    event,
                    status_code,
                    1 if success else 0,
                    error,
                    attempt,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def query(self, webhook_id: str | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            if webhook_id:
                rows = self._conn.execute(
                    "SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY delivered_at DESC LIMIT ?",
                    (webhook_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM webhook_deliveries ORDER BY delivered_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "delivery_id": row["delivery_id"],
                "webhook_id": row["webhook_id"],
                "event": row["event"],
                "status_code": row["status_code"],
                "success": bool(row["success"]),
                "error": row["error"],
                "attempt": row["attempt"],
                "delivered_at": row["delivered_at"],
            }
            for row in rows
        ]


# ---------------------------------------------------------------------------
# SqlitePolicyStore
# ---------------------------------------------------------------------------

class SqlitePolicyStore(_SqliteBase, AbstractPolicyStore):

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
        self._conn.commit()

    def add(self, policy: DisclosurePolicy) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO policies "
                "(name, include_tags, exclude_tags, min_confidence, redact_properties, max_nodes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
            self._conn.commit()

    def get(self, name: str) -> DisclosurePolicy | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM policies WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_policy(row)

    def list_all(self) -> list[DisclosurePolicy]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM policies ORDER BY name").fetchall()
        return [self._row_to_policy(row) for row in rows]

    def update(self, name: str, policy: DisclosurePolicy) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT name FROM policies WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return False
            if policy.name != name:
                self._conn.execute("DELETE FROM policies WHERE name = ?", (name,))
            self._conn.execute(
                "INSERT OR REPLACE INTO policies "
                "(name, include_tags, exclude_tags, min_confidence, redact_properties, max_nodes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
            self._conn.commit()
            return True

    def delete(self, name: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM policies WHERE name = ?", (name,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_policy(row: sqlite3.Row) -> DisclosurePolicy:
        return DisclosurePolicy(
            name=row["name"],
            include_tags=json.loads(row["include_tags"]),
            exclude_tags=json.loads(row["exclude_tags"]),
            min_confidence=row["min_confidence"],
            redact_properties=json.loads(row["redact_properties"]),
            max_nodes=row["max_nodes"],
        )


# ---------------------------------------------------------------------------
# SqliteConnectorStore
# ---------------------------------------------------------------------------

class SqliteConnectorStore(_SqliteBase, AbstractConnectorStore):
    """Connector account links backed by SQLite."""

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS connectors (
                connector_id      TEXT PRIMARY KEY,
                provider          TEXT NOT NULL,
                account_label     TEXT NOT NULL DEFAULT '',
                external_user_id  TEXT NOT NULL DEFAULT '',
                scopes            TEXT NOT NULL DEFAULT '[]',
                status            TEXT NOT NULL DEFAULT 'active',
                metadata          TEXT NOT NULL DEFAULT '{}',
                created_at        TEXT NOT NULL DEFAULT '',
                updated_at        TEXT NOT NULL DEFAULT '',
                last_sync_at      TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

    def add(self, connector: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO connectors "
                "(connector_id, provider, account_label, external_user_id, scopes, status, metadata, "
                "created_at, updated_at, last_sync_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    connector["connector_id"],
                    connector["provider"],
                    connector.get("account_label", ""),
                    connector.get("external_user_id", ""),
                    json.dumps(connector.get("scopes", [])),
                    connector.get("status", "active"),
                    json.dumps(connector.get("metadata", {})),
                    connector.get("created_at", ""),
                    connector.get("updated_at", ""),
                    connector.get("last_sync_at", ""),
                ),
            )
            self._conn.commit()

    def get(self, connector_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM connectors WHERE connector_id = ?", (connector_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_connector(row)

    def list_all(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connectors ORDER BY created_at"
            ).fetchall()
        return [self._row_to_connector(row) for row in rows]

    def update(self, connector_id: str, updates: dict) -> dict | None:
        current = self.get(connector_id)
        if current is None:
            return None
        merged = dict(current)
        merged.update(updates)
        merged["connector_id"] = connector_id
        self.add(merged)
        return merged

    def delete(self, connector_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM connectors WHERE connector_id = ?", (connector_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_connector(row: sqlite3.Row) -> dict:
        try:
            scopes = json.loads(row["scopes"])
        except (json.JSONDecodeError, TypeError):
            scopes = []
        try:
            metadata = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return {
            "connector_id": row["connector_id"],
            "provider": row["provider"],
            "account_label": row["account_label"],
            "external_user_id": row["external_user_id"],
            "scopes": scopes,
            "status": row["status"],
            "metadata": metadata,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_sync_at": row["last_sync_at"],
        }
