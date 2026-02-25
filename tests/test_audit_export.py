"""
Tests for audit log export — JSON/CSV formatting, time parsing, API endpoint.
"""

import csv
import io
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer

import pytest

from cortex.caas.audit_export import export_csv, export_json, filter_since, parse_since
from cortex.caas.audit_ledger import InMemoryAuditLedger
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import InMemoryAuditLog, JsonWebhookStore
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import VALID_SCOPES, GrantToken


# ============================================================================
# Unit tests — parse_since
# ============================================================================

class TestParseSince:

    def test_days(self):
        dt = parse_since("7d")
        now = datetime.now(timezone.utc)
        diff = now - dt
        assert 6 < diff.total_seconds() / 86400 < 8

    def test_hours(self):
        dt = parse_since("24h")
        now = datetime.now(timezone.utc)
        diff = now - dt
        assert 23 < diff.total_seconds() / 3600 < 25

    def test_minutes(self):
        dt = parse_since("30m")
        now = datetime.now(timezone.utc)
        diff = now - dt
        assert 29 < diff.total_seconds() / 60 < 31

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid time format"):
            parse_since("abc")

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="Invalid time format"):
            parse_since("10s")


# ============================================================================
# Unit tests — export_json, export_csv
# ============================================================================

class TestExportJson:

    def test_empty(self):
        result = export_json([])
        assert json.loads(result) == []

    def test_with_entries(self):
        entries = [{"sequence_id": 0, "event_type": "test", "timestamp": "2026-01-01T00:00:00"}]
        result = export_json(entries)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["event_type"] == "test"


class TestExportCsv:

    def test_empty(self):
        result = export_csv([])
        assert "sequence_id" in result  # header row present
        lines = result.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_with_entries(self):
        entries = [{
            "sequence_id": 0,
            "timestamp": "2026-01-01T00:00:00",
            "event_type": "test",
            "actor": "system",
            "request_id": "req-1",
            "details": {"key": "value"},
            "prev_hash": "0" * 64,
            "entry_hash": "a" * 64,
        }]
        result = export_csv(entries)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "test"
        assert '"key"' in rows[0]["details"]


# ============================================================================
# Unit tests — filter_since
# ============================================================================

class TestFilterSince:

    def test_filters_old_entries(self):
        old = "2020-01-01T00:00:00+00:00"
        recent = datetime.now(timezone.utc).isoformat()
        entries = [
            {"timestamp": old, "event_type": "old"},
            {"timestamp": recent, "event_type": "new"},
        ]
        since = datetime.now(timezone.utc) - timedelta(days=1)
        result = filter_since(entries, since)
        assert len(result) == 1
        assert result[0]["event_type"] == "new"


# ============================================================================
# Integration test — /audit/export endpoint
# ============================================================================

def _build_test_graph():
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    return g


def _setup_server_with_audit():
    if not has_crypto():
        return None, None, None, None, None

    identity = UPAIIdentity.generate("Test User")
    graph = _build_test_graph()
    audit = InMemoryAuditLog()

    from cortex.upai.disclosure import PolicyRegistry

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.audit_log = audit
    CaaSHandler.rate_limiter = None
    CaaSHandler.login_rate_limiter = None
    CaaSHandler.webhook_worker = None
    CaaSHandler.metrics_registry = None
    CaaSHandler.session_manager = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = None
    CaaSHandler.sse_manager = None
    CaaSHandler.keychain = None
    CaaSHandler.policy_registry = PolicyRegistry()
    CaaSHandler._allowed_origins = set()
    CaaSHandler.hsts_enabled = False

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    token = GrantToken.create(identity, audience="Test", scopes=list(VALID_SCOPES))
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str, audit


class TestAuditExportEndpoint:

    def test_export_json(self):
        server, port, identity, token_str, audit = _setup_server_with_audit()
        if server is None:
            return
        try:
            # Create some audit entries by making API calls
            url = f"http://127.0.0.1:{port}/audit/export?format=json"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token_str}")
            resp = urllib.request.urlopen(req)
            assert resp.status == 200
            content_type = resp.headers.get("Content-Type")
            assert "application/json" in content_type
            disp = resp.headers.get("Content-Disposition")
            assert "audit_export.json" in disp
            data = json.loads(resp.read())
            assert isinstance(data, list)
        finally:
            CaaSHandler.audit_log = None
            server.shutdown()

    def test_export_csv(self):
        server, port, identity, token_str, audit = _setup_server_with_audit()
        if server is None:
            return
        try:
            url = f"http://127.0.0.1:{port}/audit/export?format=csv"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token_str}")
            resp = urllib.request.urlopen(req)
            assert resp.status == 200
            content_type = resp.headers.get("Content-Type")
            assert "text/csv" in content_type
            disp = resp.headers.get("Content-Disposition")
            assert "audit_export.csv" in disp
            body = resp.read().decode("utf-8")
            assert "sequence_id" in body  # CSV header
        finally:
            CaaSHandler.audit_log = None
            server.shutdown()

    def test_export_invalid_format_returns_400(self):
        server, port, identity, token_str, audit = _setup_server_with_audit()
        if server is None:
            return
        try:
            url = f"http://127.0.0.1:{port}/audit/export?format=xml"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token_str}")
            try:
                urllib.request.urlopen(req)
                assert False, "Should have raised HTTPError"
            except urllib.error.HTTPError as e:
                assert e.code == 400
        finally:
            CaaSHandler.audit_log = None
            server.shutdown()
