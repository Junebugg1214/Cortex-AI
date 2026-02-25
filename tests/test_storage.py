"""
Tests for CaaS storage backends — JSON (in-memory) and SQLite.

Parametrized across both backends to ensure identical behavior.
"""

import tempfile
import threading
from pathlib import Path

import pytest

from cortex.caas.server import JsonGrantStore
from cortex.caas.sqlite_store import (
    SqliteAuditLog,
    SqliteDeliveryLog,
    SqliteGrantStore,
    SqliteWebhookStore,
)
from cortex.caas.storage import InMemoryAuditLog, JsonWebhookStore
from cortex.upai.webhooks import create_webhook

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(params=["json", "sqlite"])
def grant_store(request, tmpdir):
    if request.param == "json":
        return JsonGrantStore(persist_path=str(Path(tmpdir) / "grants.json"))
    else:
        return SqliteGrantStore(str(Path(tmpdir) / "test.db"))


@pytest.fixture(params=["json", "sqlite"])
def webhook_store(request, tmpdir):
    if request.param == "json":
        return JsonWebhookStore()
    else:
        return SqliteWebhookStore(str(Path(tmpdir) / "test.db"))


@pytest.fixture(params=["memory", "sqlite"])
def audit_log(request, tmpdir):
    if request.param == "memory":
        return InMemoryAuditLog()
    else:
        return SqliteAuditLog(str(Path(tmpdir) / "test.db"))


def _make_token_data(audience="TestAudience", policy="professional"):
    return {
        "audience": audience,
        "policy": policy,
        "issued_at": "2026-01-01T00:00:00Z",
        "scopes": ["context:read"],
    }


# ============================================================================
# Grant store tests
# ============================================================================

class TestGrantStore:

    def test_add_and_get(self, grant_store):
        td = _make_token_data()
        grant_store.add("g1", "tok1", td)
        result = grant_store.get("g1")
        assert result is not None
        assert result["token_str"] == "tok1"
        assert result["revoked"] is False

    def test_get_nonexistent(self, grant_store):
        assert grant_store.get("nope") is None

    def test_list_all(self, grant_store):
        grant_store.add("g1", "tok1", _make_token_data(audience="A"))
        grant_store.add("g2", "tok2", _make_token_data(audience="B"))
        grants = grant_store.list_all()
        assert len(grants) == 2
        ids = {g["grant_id"] for g in grants}
        assert ids == {"g1", "g2"}

    def test_revoke(self, grant_store):
        grant_store.add("g1", "tok1", _make_token_data())
        assert grant_store.revoke("g1") is True
        result = grant_store.get("g1")
        assert result["revoked"] is True

    def test_revoke_nonexistent(self, grant_store):
        assert grant_store.revoke("nope") is False

    def test_list_shows_revoked_status(self, grant_store):
        grant_store.add("g1", "tok1", _make_token_data())
        grant_store.revoke("g1")
        grants = grant_store.list_all()
        assert grants[0]["revoked"] is True


class TestGrantStorePersistence:

    def test_json_persistence(self, tmpdir):
        path = str(Path(tmpdir) / "grants.json")
        gs1 = JsonGrantStore(persist_path=path)
        gs1.add("g1", "tok1", _make_token_data())
        # New instance reads from same file
        gs2 = JsonGrantStore(persist_path=path)
        assert gs2.get("g1") is not None

    def test_sqlite_persistence(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        gs1 = SqliteGrantStore(db)
        gs1.add("g1", "tok1", _make_token_data())
        gs1.close()
        gs2 = SqliteGrantStore(db)
        assert gs2.get("g1") is not None


class TestGrantStoreThreadSafety:

    def test_concurrent_adds(self, grant_store):
        errors = []
        def adder(i):
            try:
                grant_store.add(f"g{i}", f"tok{i}", _make_token_data(audience=f"A{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=adder, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(grant_store.list_all()) == 10


# ============================================================================
# Webhook store tests
# ============================================================================

class TestWebhookStore:

    def test_add_and_get(self, webhook_store):
        reg = create_webhook("https://example.com/hook", ["grant.created"])
        webhook_store.add(reg)
        result = webhook_store.get(reg.webhook_id)
        assert result is not None
        assert result.url == "https://example.com/hook"

    def test_get_nonexistent(self, webhook_store):
        assert webhook_store.get("nope") is None

    def test_list_all(self, webhook_store):
        r1 = create_webhook("https://example.com/a", ["grant.created"])
        r2 = create_webhook("https://example.com/b", ["grant.revoked"])
        webhook_store.add(r1)
        webhook_store.add(r2)
        all_hooks = webhook_store.list_all()
        assert len(all_hooks) == 2

    def test_delete(self, webhook_store):
        reg = create_webhook("https://example.com/hook", ["grant.created"])
        webhook_store.add(reg)
        assert webhook_store.delete(reg.webhook_id) is True
        assert webhook_store.get(reg.webhook_id) is None

    def test_delete_nonexistent(self, webhook_store):
        assert webhook_store.delete("nope") is False

    def test_get_for_event(self, webhook_store):
        r1 = create_webhook("https://example.com/a", ["grant.created"])
        r2 = create_webhook("https://example.com/b", ["grant.revoked"])
        r3 = create_webhook("https://example.com/c", ["grant.created", "grant.revoked"])
        webhook_store.add(r1)
        webhook_store.add(r2)
        webhook_store.add(r3)
        hooks = webhook_store.get_for_event("grant.created")
        assert len(hooks) == 2
        urls = {h.url for h in hooks}
        assert "https://example.com/a" in urls
        assert "https://example.com/c" in urls


class TestWebhookStoreThreadSafety:

    def test_concurrent_adds(self, webhook_store):
        errors = []
        def adder(i):
            try:
                reg = create_webhook(f"https://example.com/{i}", ["grant.created"])
                webhook_store.add(reg)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=adder, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(webhook_store.list_all()) == 10


# ============================================================================
# Audit log tests
# ============================================================================

class TestAuditLog:

    def test_log_and_query(self, audit_log):
        audit_log.log("grant.created", {"grant_id": "g1"})
        audit_log.log("grant.revoked", {"grant_id": "g1"})
        entries = audit_log.query()
        assert len(entries) == 2

    def test_query_by_event_type(self, audit_log):
        audit_log.log("grant.created", {"grant_id": "g1"})
        audit_log.log("grant.revoked", {"grant_id": "g2"})
        audit_log.log("grant.created", {"grant_id": "g3"})
        entries = audit_log.query(event_type="grant.created")
        assert len(entries) == 2

    def test_query_limit(self, audit_log):
        for i in range(10):
            audit_log.log("event", {"i": i})
        entries = audit_log.query(limit=5)
        assert len(entries) == 5

    def test_empty_query(self, audit_log):
        entries = audit_log.query()
        assert entries == []


# ============================================================================
# Delivery log tests (SQLite only)
# ============================================================================

class TestDeliveryLog:

    def test_record_and_query(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        dl = SqliteDeliveryLog(db)
        dl.record("d1", "w1", "grant.created", 200, True)
        dl.record("d2", "w1", "grant.revoked", 500, False, error="server error")
        entries = dl.query()
        assert len(entries) == 2

    def test_query_by_webhook_id(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        dl = SqliteDeliveryLog(db)
        dl.record("d1", "w1", "grant.created", 200, True)
        dl.record("d2", "w2", "grant.revoked", 200, True)
        entries = dl.query(webhook_id="w1")
        assert len(entries) == 1
        assert entries[0]["webhook_id"] == "w1"

    def test_success_flag(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        dl = SqliteDeliveryLog(db)
        dl.record("d1", "w1", "grant.created", 200, True)
        dl.record("d2", "w1", "grant.created", 0, False, error="timeout")
        entries = dl.query()
        successes = [e for e in entries if e["success"]]
        failures = [e for e in entries if not e["success"]]
        assert len(successes) == 1
        assert len(failures) == 1


# ============================================================================
# SQLite WAL tuning PRAGMAs
# ============================================================================

class TestSqliteWALTuning:
    """Verify performance-tuning PRAGMAs are set on new SQLite stores."""

    def test_synchronous_normal(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        gs = SqliteGrantStore(db)
        row = gs._conn.execute("PRAGMA synchronous").fetchone()
        # synchronous=NORMAL is mode 1
        assert row[0] == 1
        gs.close()

    def test_cache_size_8mb(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        gs = SqliteGrantStore(db)
        row = gs._conn.execute("PRAGMA cache_size").fetchone()
        # Negative value means KiB: -8000 => ~8MB
        assert row[0] == -8000
        gs.close()

    def test_wal_mode_still_enabled(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        gs = SqliteGrantStore(db)
        row = gs._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        gs.close()

    def test_foreign_keys_still_on(self, tmpdir):
        db = str(Path(tmpdir) / "test.db")
        gs = SqliteGrantStore(db)
        row = gs._conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
        gs.close()
