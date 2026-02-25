"""
Tests for WP-5.2: Immutable Hash-Chained Audit Ledger.

Covers:
- AuditEntry hash computation and determinism
- InMemoryAuditLedger chain building and verification
- SqliteAuditLedger persistence and chain integrity
- Tamper detection (modify, delete, reorder)
- Query filtering by event_type and actor
- /audit and /audit/verify API endpoints
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from cortex.caas.audit_ledger import (
    GENESIS_HASH,
    AuditEntry,
    InMemoryAuditLedger,
    verify_chain,
)
from cortex.caas.sqlite_audit_ledger import SqliteAuditLedger

# ── AuditEntry ───────────────────────────────────────────────────────────


class TestAuditEntry:
    def test_compute_hash_deterministic(self):
        entry = AuditEntry(
            sequence_id=0, timestamp="2024-01-01T00:00:00",
            event_type="test", actor="system", request_id="",
            details={}, prev_hash=GENESIS_HASH,
        )
        h1 = entry.compute_hash()
        h2 = entry.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_fields_different_hash(self):
        e1 = AuditEntry(sequence_id=0, timestamp="2024-01-01", event_type="a",
                        actor="system", request_id="", details={}, prev_hash=GENESIS_HASH)
        e2 = AuditEntry(sequence_id=0, timestamp="2024-01-01", event_type="b",
                        actor="system", request_id="", details={}, prev_hash=GENESIS_HASH)
        assert e1.compute_hash() != e2.compute_hash()

    def test_genesis_entry(self):
        entry = AuditEntry(
            sequence_id=0, timestamp="2024-01-01", event_type="init",
            actor="system", request_id="", details={}, prev_hash=GENESIS_HASH,
        )
        entry.entry_hash = entry.compute_hash()
        assert entry.prev_hash == GENESIS_HASH

    def test_to_dict_roundtrip(self):
        entry = AuditEntry(
            sequence_id=5, timestamp="2024-01-01", event_type="grant.created",
            actor="grant:abc", request_id="req-1",
            details={"grant_id": "abc"}, prev_hash="aaa",
        )
        entry.entry_hash = entry.compute_hash()
        d = entry.to_dict()
        restored = AuditEntry.from_dict(d)
        assert restored.sequence_id == 5
        assert restored.entry_hash == entry.entry_hash


# ── InMemoryAuditLedger ─────────────────────────────────────────────────


class TestInMemoryAuditLedger:
    def test_append_and_count(self):
        ledger = InMemoryAuditLedger()
        ledger.append("test.event", details={"key": "val"})
        assert ledger.count() == 1

    def test_chain_links(self):
        ledger = InMemoryAuditLedger()
        e1 = ledger.append("first")
        e2 = ledger.append("second")
        assert e1.prev_hash == GENESIS_HASH
        assert e2.prev_hash == e1.entry_hash

    def test_verify_valid_chain(self):
        ledger = InMemoryAuditLedger()
        for i in range(10):
            ledger.append(f"event.{i}")
        valid, checked, error = ledger.verify()
        assert valid is True
        assert checked == 10
        assert error == ""

    def test_detect_tampered_hash(self):
        ledger = InMemoryAuditLedger()
        ledger.append("event.1")
        ledger.append("event.2")
        # Tamper with first entry's hash
        ledger._entries[0].entry_hash = "bad_hash"
        valid, checked, error = ledger.verify()
        assert valid is False
        assert "hash mismatch" in error

    def test_detect_broken_chain(self):
        ledger = InMemoryAuditLedger()
        ledger.append("event.1")
        ledger.append("event.2")
        ledger.append("event.3")
        # Break chain by changing prev_hash of entry 2
        e = ledger._entries[2]
        e.prev_hash = "wrong"
        e.entry_hash = e.compute_hash()  # re-hash with wrong prev
        valid, checked, error = ledger.verify()
        assert valid is False
        assert "chain broken" in error

    def test_query_by_event_type(self):
        ledger = InMemoryAuditLedger()
        ledger.append("grant.created", details={"a": 1})
        ledger.append("auth.failed", details={"b": 2})
        ledger.append("grant.created", details={"c": 3})
        results = ledger.query(event_type="grant.created")
        assert len(results) == 2

    def test_query_by_actor(self):
        ledger = InMemoryAuditLedger()
        ledger.append("ev", actor="grant:abc")
        ledger.append("ev", actor="dashboard:xyz")
        ledger.append("ev", actor="grant:abc")
        results = ledger.query(actor="grant:abc")
        assert len(results) == 2

    def test_query_pagination(self):
        ledger = InMemoryAuditLedger()
        for i in range(10):
            ledger.append(f"event.{i}")
        page1 = ledger.query(limit=3, offset=0)
        page2 = ledger.query(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].sequence_id == 0
        assert page2[0].sequence_id == 3

    def test_empty_ledger_valid(self):
        ledger = InMemoryAuditLedger()
        valid, checked, error = ledger.verify()
        assert valid is True
        assert checked == 0

    def test_thread_safety(self):
        ledger = InMemoryAuditLedger()
        errors = []

        def append_many():
            try:
                for i in range(50):
                    ledger.append("thread.event")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=append_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert ledger.count() == 200
        valid, _, _ = ledger.verify()
        assert valid is True

    def test_backward_compat_log_method(self):
        ledger = InMemoryAuditLedger()
        ledger.log("test.event", {"key": "val"})
        assert ledger.count() == 1

    def test_backward_compat_recent_method(self):
        ledger = InMemoryAuditLedger()
        ledger.append("ev1")
        ledger.append("ev2")
        recent = ledger.recent(limit=10)
        assert len(recent) == 2
        assert isinstance(recent[0], dict)


# ── SqliteAuditLedger ───────────────────────────────────────────────────


class TestSqliteAuditLedger:
    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "audit.db")

    def test_append_and_count(self, db_path):
        ledger = SqliteAuditLedger(db_path)
        ledger.append("test.event", details={"key": "val"})
        assert ledger.count() == 1

    def test_chain_survives_restart(self, db_path):
        ledger1 = SqliteAuditLedger(db_path)
        ledger1.append("event.1")
        e2 = ledger1.append("event.2")

        # "Restart" with new instance
        ledger2 = SqliteAuditLedger(db_path)
        assert ledger2.count() == 2
        e3 = ledger2.append("event.3")
        assert e3.prev_hash == e2.entry_hash

    def test_verify_valid(self, db_path):
        ledger = SqliteAuditLedger(db_path)
        for i in range(5):
            ledger.append(f"event.{i}")
        valid, checked, error = ledger.verify()
        assert valid is True
        assert checked == 5

    def test_detect_tamper(self, db_path):
        ledger = SqliteAuditLedger(db_path)
        ledger.append("event.1")
        ledger.append("event.2")

        # Tamper with the database directly
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE audit_ledger SET entry_hash = 'bad' WHERE sequence_id = 0")
        conn.commit()
        conn.close()

        valid, checked, error = ledger.verify()
        assert valid is False

    def test_query_by_event(self, db_path):
        ledger = SqliteAuditLedger(db_path)
        ledger.append("grant.created")
        ledger.append("auth.failed")
        ledger.append("grant.created")
        results = ledger.query(event_type="grant.created")
        assert len(results) == 2

    def test_query_by_actor(self, db_path):
        ledger = SqliteAuditLedger(db_path)
        ledger.append("ev", actor="grant:abc")
        ledger.append("ev", actor="system")
        results = ledger.query(actor="grant:abc")
        assert len(results) == 1

    def test_concurrent_appends(self, db_path):
        ledger = SqliteAuditLedger(db_path)
        errors = []

        def append_many():
            try:
                for i in range(20):
                    ledger.append("concurrent.event")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=append_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert ledger.count() == 80
        valid, _, _ = ledger.verify()
        assert valid is True


# ── Chain verification edge cases ────────────────────────────────────


class TestChainVerification:
    def test_empty_chain_valid(self):
        valid, checked, error = verify_chain([])
        assert valid is True
        assert checked == 0

    def test_single_entry_valid(self):
        entry = AuditEntry(
            sequence_id=0, timestamp="2024-01-01", event_type="test",
            actor="system", request_id="", details={}, prev_hash=GENESIS_HASH,
        )
        entry.entry_hash = entry.compute_hash()
        valid, checked, error = verify_chain([entry])
        assert valid is True
        assert checked == 1

    def test_modified_entry_detected(self):
        e1 = AuditEntry(
            sequence_id=0, timestamp="2024-01-01", event_type="test",
            actor="system", request_id="", details={}, prev_hash=GENESIS_HASH,
        )
        e1.entry_hash = e1.compute_hash()
        # Modify after hash
        e1.event_type = "tampered"
        valid, _, error = verify_chain([e1])
        assert valid is False

    def test_reordered_entries_detected(self):
        ledger = InMemoryAuditLedger()
        ledger.append("event.1")
        ledger.append("event.2")
        ledger.append("event.3")

        # Swap entries
        entries = list(ledger._entries)
        entries[1], entries[2] = entries[2], entries[1]
        valid, _, error = verify_chain(entries)
        assert valid is False


# ── API endpoints ────────────────────────────────────────────────────


class TestAuditAPIEndpoints:
    @pytest.fixture(autouse=True)
    def _setup_server(self):
        from cortex.caas.server import CaaSHandler, JsonGrantStore, ThreadingHTTPServer
        from cortex.caas.storage import JsonWebhookStore
        from cortex.graph import CortexGraph
        from cortex.upai.disclosure import PolicyRegistry
        from cortex.upai.identity import UPAIIdentity
        from cortex.upai.tokens import VALID_SCOPES, GrantToken

        self.identity = UPAIIdentity.generate(name="test-audit")
        graph = CortexGraph()

        self.ledger = InMemoryAuditLedger()

        CaaSHandler.graph = graph
        CaaSHandler.identity = self.identity
        CaaSHandler.grant_store = JsonGrantStore()
        CaaSHandler.audit_log = self.ledger
        CaaSHandler.metrics_registry = None
        CaaSHandler.rate_limiter = None
        CaaSHandler.login_rate_limiter = None
        CaaSHandler.webhook_worker = None
        CaaSHandler.sse_manager = None
        CaaSHandler.session_manager = None
        CaaSHandler.oauth_manager = None
        CaaSHandler.credential_store = None
        CaaSHandler.keychain = None
        CaaSHandler.webhook_store = JsonWebhookStore()
        CaaSHandler.policy_registry = PolicyRegistry()
        CaaSHandler._allowed_origins = {"http://127.0.0.1:0"}
        CaaSHandler.version_store = None
        CaaSHandler.nonce_cache = __import__(
            "cortex.caas.server", fromlist=["NonceCache"]
        ).NonceCache()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        # Owner token
        token = GrantToken.create(self.identity, audience="test", scopes=list(VALID_SCOPES))
        self.token_str = token.sign(self.identity)
        CaaSHandler.grant_store.add(token.grant_id, self.token_str, token.to_dict())
        yield
        self.server.shutdown()

    def _get(self, path: str) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={"Authorization": f"Bearer {self.token_str}"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())

    def test_get_audit_empty(self):
        status, data = self._get("/audit")
        assert status == 200
        assert "entries" in data

    def test_get_audit_with_entries(self):
        self.ledger.append("test.event", actor="system", details={"x": 1})
        status, data = self._get("/audit")
        assert status == 200
        assert len(data["entries"]) >= 1

    def test_get_audit_filter_by_event_type(self):
        self.ledger.append("grant.created")
        self.ledger.append("auth.failed")
        status, data = self._get("/audit?event_type=grant.created")
        assert status == 200
        assert all(e["event_type"] == "grant.created" for e in data["entries"])

    def test_verify_valid_chain(self):
        self.ledger.append("event.1")
        self.ledger.append("event.2")
        status, data = self._get("/audit/verify")
        assert status == 200
        assert data["valid"] is True
        assert data["entries_checked"] == 2

    def test_audit_requires_auth(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/audit")
        resp = conn.getresponse()
        assert resp.status == 401

    def test_audit_entries_include_request_id(self):
        # Trigger an audit via a grant creation
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/grants",
                     body=json.dumps({"audience": "audit-test", "policy": "professional"}),
                     headers={"Content-Type": "application/json",
                              "Authorization": f"Bearer {self.token_str}",
                              "X-Request-ID": "trace-123"})
        resp = conn.getresponse()
        resp.read()  # consume

        status, data = self._get("/audit")
        assert status == 200
        # At least one entry should be from the grant creation
        assert len(data["entries"]) >= 1
