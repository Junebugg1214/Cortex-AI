"""
CaaS Schema Migrations — Lightweight migration framework for SQLite.

Simple version table + ordered SQL migrations. Each migration is applied
exactly once in a transaction. No external dependencies.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

_log = logging.getLogger("caas.migrations")


# ---------------------------------------------------------------------------
# Migration dataclass
# ---------------------------------------------------------------------------

@dataclass
class Migration:
    """A single schema migration."""
    version: int
    description: str
    up_sql: str


# ---------------------------------------------------------------------------
# Migration registry (built-in migrations)
# ---------------------------------------------------------------------------

_MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        description="Baseline — mark existing schema as v1",
        up_sql="-- baseline migration: no schema changes",
    ),
    Migration(
        version=2,
        description="Encryption support available — no schema changes needed",
        up_sql="-- encryption: encrypted values stored in existing TEXT columns",
    ),
    Migration(
        version=3,
        description="Connector account links table",
        up_sql="""
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
        """,
    ),
]


def register_migration(version: int, description: str, up_sql: str) -> None:
    """Register a custom migration (for extensions)."""
    _MIGRATIONS.append(Migration(version=version, description=description, up_sql=up_sql))
    _MIGRATIONS.sort(key=lambda m: m.version)


# ---------------------------------------------------------------------------
# MigrationRunner
# ---------------------------------------------------------------------------

class MigrationRunner:
    """Runs schema migrations against a SQLite database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        """Create the schema_versions table if it doesn't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                version     INTEGER PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                applied_at  TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

    def current_version(self) -> int:
        """Return the highest applied migration version, or 0 if none."""
        row = self._conn.execute(
            "SELECT MAX(version) FROM schema_versions"
        ).fetchone()
        return row[0] if row[0] is not None else 0

    def pending(self) -> list[Migration]:
        """Return list of migrations not yet applied."""
        current = self.current_version()
        return [m for m in _MIGRATIONS if m.version > current]

    def migrate(self) -> int:
        """Apply all pending migrations in order. Returns count applied.

        Each migration runs within a transaction. If a migration fails,
        its transaction is rolled back and no further migrations are applied.
        """
        with self._lock:
            applied = 0
            for migration in self.pending():
                try:
                    self._apply(migration)
                    applied += 1
                    _log.info("Applied migration v%d: %s", migration.version, migration.description)
                except Exception as e:
                    _log.error("Migration v%d failed: %s", migration.version, e)
                    raise
            return applied

    def _apply(self, migration: Migration) -> None:
        """Apply a single migration within a transaction."""
        now = datetime.now(timezone.utc).isoformat()
        # Execute migration SQL (may be a no-op comment)
        sql = migration.up_sql.strip()
        if sql and not sql.startswith("--"):
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    self._conn.execute(statement)
        # Record version
        self._conn.execute(
            "INSERT INTO schema_versions (version, description, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.description, now),
        )
        self._conn.commit()

    def is_applied(self, version: int) -> bool:
        """Check if a specific version has been applied."""
        row = self._conn.execute(
            "SELECT version FROM schema_versions WHERE version = ?", (version,)
        ).fetchone()
        return row is not None
