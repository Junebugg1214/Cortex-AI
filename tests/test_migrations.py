"""Tests for cortex.caas.migrations — Schema migration framework."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from cortex.caas.migrations import Migration, MigrationRunner, _MIGRATIONS, register_migration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_conn(tmp_path: Path | None = None) -> sqlite3.Connection:
    """Create a fresh in-memory SQLite connection."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# TestMigrationRunner
# ---------------------------------------------------------------------------

class TestMigrationRunner:
    def test_creates_version_table(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        # Should have schema_versions table
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_versions'"
        ).fetchone()
        assert row is not None
        conn.close()

    def test_fresh_db_version_zero(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        assert runner.current_version() == 0
        conn.close()

    def test_pending_returns_all_on_fresh_db(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        pending = runner.pending()
        assert len(pending) == len(_MIGRATIONS)
        conn.close()

    def test_migrate_applies_all(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        count = runner.migrate()
        assert count == len(_MIGRATIONS)
        assert runner.current_version() == _MIGRATIONS[-1].version
        conn.close()

    def test_migrate_idempotent(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        count1 = runner.migrate()
        count2 = runner.migrate()
        assert count1 == len(_MIGRATIONS)
        assert count2 == 0  # Already applied
        conn.close()

    def test_is_applied(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        assert not runner.is_applied(1)
        runner.migrate()
        assert runner.is_applied(1)
        assert runner.is_applied(2)
        conn.close()

    def test_pending_after_partial(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        # Manually apply v1 only
        runner._apply(_MIGRATIONS[0])
        assert runner.current_version() == 1
        pending = runner.pending()
        assert all(m.version > 1 for m in pending)
        conn.close()

    def test_version_tracking(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        runner.migrate()
        rows = conn.execute("SELECT * FROM schema_versions ORDER BY version").fetchall()
        assert len(rows) == len(_MIGRATIONS)
        for row, migration in zip(rows, _MIGRATIONS):
            assert row["version"] == migration.version
            assert row["description"] == migration.description
            assert row["applied_at"] != ""
        conn.close()


# ---------------------------------------------------------------------------
# TestMigrationOrder
# ---------------------------------------------------------------------------

class TestMigrationOrder:
    def test_migrations_are_ordered(self):
        versions = [m.version for m in _MIGRATIONS]
        assert versions == sorted(versions)

    def test_no_duplicate_versions(self):
        versions = [m.version for m in _MIGRATIONS]
        assert len(versions) == len(set(versions))

    def test_builtin_migrations_exist(self):
        assert len(_MIGRATIONS) >= 2
        assert _MIGRATIONS[0].version == 1
        assert _MIGRATIONS[1].version == 2


# ---------------------------------------------------------------------------
# TestMigrationWithRealSQL
# ---------------------------------------------------------------------------

class TestMigrationWithRealSQL:
    def test_sql_migration_creates_table(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        # Register a custom migration with actual SQL
        test_migration = Migration(
            version=999,
            description="Test: create test_table",
            up_sql="CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)",
        )
        # Apply directly
        runner._apply(test_migration)
        # Verify table was created
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        ).fetchone()
        assert row is not None
        conn.close()

    def test_multi_statement_migration(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        migration = Migration(
            version=998,
            description="Test: multi-statement",
            up_sql="""
                CREATE TABLE t1 (id INTEGER PRIMARY KEY);
                CREATE TABLE t2 (id INTEGER PRIMARY KEY)
            """,
        )
        runner._apply(migration)
        for tname in ("t1", "t2"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (tname,),
            ).fetchone()
            assert row is not None
        conn.close()

    def test_failed_migration_raises(self):
        conn = _fresh_conn()
        runner = MigrationRunner(conn)
        bad_migration = Migration(
            version=997,
            description="Bad SQL",
            up_sql="THIS IS NOT VALID SQL",
        )
        with pytest.raises(Exception):
            runner._apply(bad_migration)
        # Version should not be recorded
        assert not runner.is_applied(997)
        conn.close()


# ---------------------------------------------------------------------------
# TestSqliteStoreIntegration
# ---------------------------------------------------------------------------

class TestSqliteStoreIntegration:
    def test_grant_store_runs_migrations(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        from cortex.caas.sqlite_store import SqliteGrantStore
        store = SqliteGrantStore(db_path)
        # Verify schema_versions table exists
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_versions'"
        ).fetchone()
        assert row is not None
        # Verify migrations were applied
        runner = MigrationRunner(store._conn)
        assert runner.current_version() >= 1
        store.close()

    def test_webhook_store_runs_migrations(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        from cortex.caas.sqlite_store import SqliteWebhookStore
        store = SqliteWebhookStore(db_path)
        runner = MigrationRunner(store._conn)
        assert runner.current_version() >= 1
        store.close()

    def test_existing_db_skips_applied(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        from cortex.caas.sqlite_store import SqliteGrantStore
        # First init applies migrations
        store1 = SqliteGrantStore(db_path)
        runner1 = MigrationRunner(store1._conn)
        v1 = runner1.current_version()
        store1.close()
        # Second init should not re-apply
        store2 = SqliteGrantStore(db_path)
        runner2 = MigrationRunner(store2._conn)
        v2 = runner2.current_version()
        assert v2 == v1
        # Version table should have same number of entries
        count = store2._conn.execute("SELECT COUNT(*) FROM schema_versions").fetchone()[0]
        assert count == len(_MIGRATIONS)
        store2.close()
