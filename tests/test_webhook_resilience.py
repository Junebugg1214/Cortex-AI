"""
Tests for WP-5.3: Webhook Resilience.

Covers:
- Circuit breaker state machine (CLOSED/OPEN/HALF_OPEN)
- Jitter calculation and bounds
- Dead-letter queue (in-memory and SQLite)
- 429 Retry-After handling
- WebhookWorker circuit breaker + dead-letter integration
- Dashboard webhook health/retry API
"""

from __future__ import annotations

import json
import threading
import time
import http.client
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch

import pytest

from cortex.caas.circuit_breaker import CircuitBreaker, CircuitState
from cortex.caas.dead_letter import DeadLetterQueue, SqliteDeadLetterQueue, DeadLetterEntry
from cortex.caas.webhook_worker import WebhookWorker, _jitter, _parse_retry_after
from cortex.upai.webhooks import create_webhook, deliver_webhook
from cortex.caas.storage import JsonWebhookStore


# ── Circuit Breaker ─────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_allows_request_when_closed(self):
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_blocks_request_when_open(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_success_closes_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_failure_reopens_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_to_dict(self):
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)
        d = cb.to_dict()
        assert d["state"] == "closed"
        assert d["failure_count"] == 0
        assert d["failure_threshold"] == 5
        assert d["cooldown_seconds"] == 30.0

    def test_thread_safety(self):
        cb = CircuitBreaker(failure_threshold=100)
        errors = []

        def fail_many():
            try:
                for _ in range(50):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fail_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert cb.failure_count == 200

    def test_last_times_updated(self):
        cb = CircuitBreaker()
        assert cb.last_success_time == 0.0
        assert cb.last_failure_time == 0.0
        cb.record_failure()
        assert cb.last_failure_time > 0.0
        cb.record_success()
        assert cb.last_success_time > 0.0


# ── Jitter ──────────────────────────────────────────────────────────────


class TestJitter:
    def test_positive(self):
        delay = _jitter(2.0, 1)
        assert delay > 0

    def test_within_bounds(self):
        # base=2.0, attempt=1 → base delay = 2.0
        # jittered = 2.0 * (0.5..1.5) = 1.0..3.0
        for _ in range(50):
            delay = _jitter(2.0, 1)
            assert 0.9 <= delay <= 3.1

    def test_varies_between_calls(self):
        delays = {_jitter(2.0, 1) for _ in range(20)}
        # With 20 calls, we should get multiple distinct values
        assert len(delays) > 1

    def test_capped_at_max(self):
        delay = _jitter(10.0, 10, max_delay=5.0)
        assert delay <= 5.0

    def test_higher_attempt_larger_base(self):
        # On average, attempt=2 should be larger than attempt=1
        avg1 = sum(_jitter(2.0, 1) for _ in range(100)) / 100
        avg2 = sum(_jitter(2.0, 2) for _ in range(100)) / 100
        assert avg2 > avg1


# ── Parse Retry-After ───────────────────────────────────────────────────


class TestParseRetryAfter:
    def test_valid_seconds(self):
        assert _parse_retry_after({"Retry-After": "30"}) == 30.0

    def test_float_seconds(self):
        assert _parse_retry_after({"Retry-After": "1.5"}) == 1.5

    def test_capped_at_300(self):
        assert _parse_retry_after({"Retry-After": "600"}) == 300.0

    def test_none_headers(self):
        assert _parse_retry_after(None) is None

    def test_missing_header(self):
        assert _parse_retry_after({"Other": "value"}) is None

    def test_invalid_value(self):
        assert _parse_retry_after({"Retry-After": "not-a-number"}) is None

    def test_lowercase_header(self):
        assert _parse_retry_after({"retry-after": "10"}) == 10.0


# ── Dead-Letter Queue (In-Memory) ──────────────────────────────────────


class TestDeadLetterQueue:
    def test_push_and_count(self):
        dlq = DeadLetterQueue()
        dlq.push("wh1", "grant.created", {"id": "g1"}, "HTTP 500")
        assert dlq.count() == 1
        assert dlq.count("wh1") == 1

    def test_push_returns_entry(self):
        dlq = DeadLetterQueue()
        entry = dlq.push("wh1", "grant.created", {"id": "g1"}, "HTTP 500")
        assert isinstance(entry, DeadLetterEntry)
        assert entry.webhook_id == "wh1"
        assert entry.event == "grant.created"

    def test_list_for_webhook(self):
        dlq = DeadLetterQueue()
        dlq.push("wh1", "ev1", {}, "err")
        dlq.push("wh2", "ev2", {}, "err")
        dlq.push("wh1", "ev3", {}, "err")
        entries = dlq.list_for_webhook("wh1")
        assert len(entries) == 2
        assert all(e.webhook_id == "wh1" for e in entries)

    def test_pop_removes_entry(self):
        dlq = DeadLetterQueue()
        entry = dlq.push("wh1", "ev1", {}, "err")
        popped = dlq.pop(entry.id)
        assert popped is not None
        assert popped.id == entry.id
        assert dlq.count() == 0

    def test_pop_nonexistent(self):
        dlq = DeadLetterQueue()
        assert dlq.pop("nonexistent") is None

    def test_pop_all_for_webhook(self):
        dlq = DeadLetterQueue()
        dlq.push("wh1", "ev1", {}, "err")
        dlq.push("wh2", "ev2", {}, "err")
        dlq.push("wh1", "ev3", {}, "err")
        popped = dlq.pop_all_for_webhook("wh1")
        assert len(popped) == 2
        assert dlq.count("wh1") == 0
        assert dlq.count("wh2") == 1

    def test_count_filtered(self):
        dlq = DeadLetterQueue()
        dlq.push("wh1", "ev1", {}, "err")
        dlq.push("wh2", "ev2", {}, "err")
        assert dlq.count("wh1") == 1
        assert dlq.count("wh2") == 1
        assert dlq.count() == 2

    def test_entry_to_dict(self):
        dlq = DeadLetterQueue()
        entry = dlq.push("wh1", "ev1", {"key": "val"}, "HTTP 500", retry_count=3)
        d = entry.to_dict()
        assert d["webhook_id"] == "wh1"
        assert d["event"] == "ev1"
        assert d["data"] == {"key": "val"}
        assert d["retry_count"] == 3
        assert "failed_at" in d

    def test_thread_safety(self):
        dlq = DeadLetterQueue()
        errors = []

        def push_many():
            try:
                for i in range(50):
                    dlq.push("wh1", f"ev.{i}", {}, "err")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=push_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert dlq.count() == 200


# ── SQLite Dead-Letter Queue ───────────────────────────────────────────


class TestSqliteDeadLetterQueue:
    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "dlq.db")

    def test_push_and_count(self, db_path):
        dlq = SqliteDeadLetterQueue(db_path)
        dlq.push("wh1", "grant.created", {"id": "g1"}, "HTTP 500")
        assert dlq.count() == 1
        assert dlq.count("wh1") == 1

    def test_list_for_webhook(self, db_path):
        dlq = SqliteDeadLetterQueue(db_path)
        dlq.push("wh1", "ev1", {}, "err")
        dlq.push("wh2", "ev2", {}, "err")
        entries = dlq.list_for_webhook("wh1")
        assert len(entries) == 1
        assert entries[0].webhook_id == "wh1"

    def test_pop_removes(self, db_path):
        dlq = SqliteDeadLetterQueue(db_path)
        entry = dlq.push("wh1", "ev1", {}, "err")
        popped = dlq.pop(entry.id)
        assert popped is not None
        assert dlq.count() == 0

    def test_pop_nonexistent(self, db_path):
        dlq = SqliteDeadLetterQueue(db_path)
        assert dlq.pop("nonexistent") is None

    def test_pop_all_for_webhook(self, db_path):
        dlq = SqliteDeadLetterQueue(db_path)
        dlq.push("wh1", "ev1", {}, "err")
        dlq.push("wh2", "ev2", {}, "err")
        dlq.push("wh1", "ev3", {}, "err")
        popped = dlq.pop_all_for_webhook("wh1")
        assert len(popped) == 2
        assert dlq.count("wh1") == 0
        assert dlq.count("wh2") == 1

    def test_persists_across_instances(self, db_path):
        dlq1 = SqliteDeadLetterQueue(db_path)
        dlq1.push("wh1", "ev1", {"key": "val"}, "err")

        dlq2 = SqliteDeadLetterQueue(db_path)
        assert dlq2.count() == 1
        entries = dlq2.list_for_webhook("wh1")
        assert entries[0].data == {"key": "val"}


# ── deliver_webhook return signature ───────────────────────────────────


class TestDeliverWebhookSignature:
    def test_returns_three_tuple(self):
        reg = create_webhook("http://127.0.0.1:1/nope", ["grant.created"])
        result = deliver_webhook(reg, "grant.created", {"id": "g1"}, timeout=0.5)
        assert len(result) == 3
        success, status, headers = result
        assert success is False
        assert isinstance(headers, dict)


# ── Mock receiver for worker tests ──────────────────────────────────────


class _FailReceiver(BaseHTTPRequestHandler):
    """Mock server that always fails."""
    fail_with: int = 500
    retry_after: str = ""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(self.__class__.fail_with)
        if self.__class__.retry_after:
            self.send_header("Retry-After", self.__class__.retry_after)
        self.end_headers()

    def log_message(self, format, *args):
        pass


class _SuccessReceiver(BaseHTTPRequestHandler):
    """Mock server that always succeeds."""
    received: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.__class__.received.append(json.loads(body) if body else {})
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _start_mock(handler_cls):
    """Start a mock server. Returns (server, port)."""
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


# ── WebhookWorker integration ──────────────────────────────────────────


class TestWebhookWorkerResilience:
    def test_exhausted_retries_go_to_dead_letter(self):
        server, port = _start_mock(_FailReceiver)
        _FailReceiver.fail_with = 500
        _FailReceiver.retry_after = ""
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{port}/hook", ["grant.created"])
            store.add(reg)

            dlq = DeadLetterQueue()
            worker = WebhookWorker(
                store, max_retries=2, backoff_base=0.1,
                dead_letter_queue=dlq,
                circuit_failure_threshold=100,  # high threshold to avoid circuit trip
            )
            worker.start()
            worker.enqueue("grant.created", {"id": "g1"})
            time.sleep(2.0)
            worker.stop()

            assert dlq.count(reg.webhook_id) == 1
            entries = dlq.list_for_webhook(reg.webhook_id)
            assert entries[0].event == "grant.created"
            assert entries[0].retry_count == 2
        finally:
            server.shutdown()

    def test_circuit_opens_on_failures(self):
        server, port = _start_mock(_FailReceiver)
        _FailReceiver.fail_with = 500
        _FailReceiver.retry_after = ""
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{port}/hook", ["grant.created"])
            store.add(reg)

            dlq = DeadLetterQueue()
            worker = WebhookWorker(
                store, max_retries=1, backoff_base=0.1,
                dead_letter_queue=dlq,
                circuit_failure_threshold=2,
                circuit_cooldown=60.0,
            )
            worker.start()

            # Send 3 events — should fail and eventually open circuit
            for i in range(3):
                worker.enqueue("grant.created", {"id": f"g{i}"})
            time.sleep(2.0)
            worker.stop()

            # Circuit should be open
            health = worker.get_health(reg.webhook_id)
            assert health["circuit"]["state"] == "open"

            # Dead-letter should have entries
            assert dlq.count(reg.webhook_id) >= 1
        finally:
            server.shutdown()

    def test_circuit_open_sends_to_dead_letter_immediately(self):
        store = JsonWebhookStore()
        reg = create_webhook("http://127.0.0.1:1/nope", ["grant.created"])
        store.add(reg)

        dlq = DeadLetterQueue()
        worker = WebhookWorker(
            store, max_retries=1, backoff_base=0.1,
            dead_letter_queue=dlq,
            circuit_failure_threshold=1,
            circuit_cooldown=60.0,
        )

        # Manually open the circuit
        cb = worker._get_circuit(reg.webhook_id)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Start and enqueue — should go straight to DLQ
        worker.start()
        worker.enqueue("grant.created", {"id": "skip"})
        time.sleep(1.0)
        worker.stop()

        entries = dlq.list_for_webhook(reg.webhook_id)
        assert len(entries) >= 1
        assert entries[0].last_error == "circuit_open"

    def test_get_health(self):
        store = JsonWebhookStore()
        worker = WebhookWorker(store)
        health = worker.get_health("wh-123")
        assert health["webhook_id"] == "wh-123"
        assert "circuit" in health
        assert health["circuit"]["state"] == "closed"
        assert health["dead_letter_count"] == 0

    def test_retry_dead_letter_replays(self):
        _SuccessReceiver.received = []
        server, port = _start_mock(_SuccessReceiver)
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{port}/hook", ["grant.created"])
            store.add(reg)

            dlq = DeadLetterQueue()
            # Pre-populate dead-letter
            dlq.push(reg.webhook_id, "grant.created", {"id": "replay1"}, "HTTP 500")
            dlq.push(reg.webhook_id, "grant.created", {"id": "replay2"}, "HTTP 500")

            worker = WebhookWorker(
                store, max_retries=1, backoff_base=0.1,
                dead_letter_queue=dlq,
            )
            worker.start()

            count = worker.retry_dead_letter(reg.webhook_id)
            assert count == 2
            assert dlq.count(reg.webhook_id) == 0  # popped from DLQ

            time.sleep(2.0)
            worker.stop()

            assert len(_SuccessReceiver.received) == 2
        finally:
            server.shutdown()

    def test_success_resets_circuit(self):
        _SuccessReceiver.received = []
        server, port = _start_mock(_SuccessReceiver)
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{port}/hook", ["grant.created"])
            store.add(reg)

            worker = WebhookWorker(
                store, max_retries=1, backoff_base=0.1,
                circuit_failure_threshold=5,
            )

            # Add some failures but not enough to open
            cb = worker._get_circuit(reg.webhook_id)
            cb.record_failure()
            cb.record_failure()
            assert cb.failure_count == 2

            worker.start()
            worker.enqueue("grant.created", {"id": "g1"})
            time.sleep(1.0)
            worker.stop()

            # After success, failure count should reset
            assert cb.failure_count == 0
            assert cb.state == CircuitState.CLOSED
        finally:
            server.shutdown()


# ── 429 Handling ─────────────────────────────────────────────────────────


class Test429Handling:
    def test_429_does_not_trip_circuit(self):
        _FailReceiver.fail_with = 429
        _FailReceiver.retry_after = "0.1"
        server, port = _start_mock(_FailReceiver)
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{port}/hook", ["grant.created"])
            store.add(reg)

            dlq = DeadLetterQueue()
            worker = WebhookWorker(
                store, max_retries=2, backoff_base=0.1,
                dead_letter_queue=dlq,
                circuit_failure_threshold=1,  # would normally open
            )
            worker.start()
            worker.enqueue("grant.created", {"id": "g1"})
            time.sleep(2.0)
            worker.stop()

            # Circuit should still be closed (429 doesn't trip it)
            health = worker.get_health(reg.webhook_id)
            assert health["circuit"]["state"] == "closed"
        finally:
            _FailReceiver.fail_with = 500
            _FailReceiver.retry_after = ""
            server.shutdown()


# ── Dashboard API: Webhook Health/Retry ─────────────────────────────────


class TestWebhookHealthAPI:
    @pytest.fixture(autouse=True)
    def _setup_server(self):
        from cortex.upai.identity import UPAIIdentity
        from cortex.graph import CortexGraph, Node
        from cortex.upai.tokens import GrantToken, VALID_SCOPES
        from cortex.caas.server import CaaSHandler, ThreadingHTTPServer, JsonGrantStore
        from cortex.caas.storage import JsonWebhookStore
        from cortex.upai.disclosure import PolicyRegistry

        self.identity = UPAIIdentity.generate(name="test-webhook-health")
        graph = CortexGraph()
        graph.add_node(Node(id="n1", label="Test", tags=["identity"], confidence=0.9))

        webhook_store = JsonWebhookStore()
        dlq = DeadLetterQueue()
        self.worker = WebhookWorker(
            webhook_store, max_retries=1, backoff_base=0.1,
            dead_letter_queue=dlq,
        )
        self.worker.start()

        # Add a test webhook
        self.test_reg = create_webhook("http://127.0.0.1:1/nope", ["grant.created"])
        webhook_store.add(self.test_reg)

        # Pre-populate dead-letter
        dlq.push(self.test_reg.webhook_id, "grant.created", {"id": "g1"}, "HTTP 500")

        CaaSHandler.graph = graph
        CaaSHandler.identity = self.identity
        CaaSHandler.grant_store = JsonGrantStore()
        CaaSHandler.audit_log = None
        CaaSHandler.metrics_registry = None
        CaaSHandler.rate_limiter = None
        CaaSHandler.webhook_worker = self.worker
        CaaSHandler.sse_manager = None
        CaaSHandler.session_manager = None
        CaaSHandler.oauth_manager = None
        CaaSHandler.credential_store = None
        CaaSHandler.keychain = None
        CaaSHandler.webhook_store = webhook_store
        CaaSHandler.policy_registry = PolicyRegistry()
        CaaSHandler._allowed_origins = {"http://127.0.0.1:0"}
        CaaSHandler.version_store = None
        CaaSHandler.nonce_cache = __import__(
            "cortex.caas.server", fromlist=["NonceCache"]
        ).NonceCache()

        # Create a dashboard session
        from cortex.caas.dashboard.auth import DashboardSessionManager
        self.session_mgr = DashboardSessionManager(self.identity)
        CaaSHandler.session_manager = self.session_mgr
        self.session_token = self.session_mgr.authenticate(self.session_mgr.password)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        yield
        self.worker.stop()
        self.server.shutdown()

    def _get(self, path: str) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={
            "Cookie": f"cortex_session={self.session_token}",
        })
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())

    def _post(self, path: str) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, headers={
            "Cookie": f"cortex_session={self.session_token}",
            "Content-Type": "application/json",
        })
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())

    def test_get_webhook_health(self):
        wid = self.test_reg.webhook_id
        status, data = self._get(f"/dashboard/api/webhooks/{wid}/health")
        assert status == 200
        assert data["webhook_id"] == wid
        assert data["circuit"]["state"] == "closed"
        assert data["dead_letter_count"] == 1

    def test_post_webhook_retry(self):
        wid = self.test_reg.webhook_id
        # Verify DLQ has entries before retry
        assert self.worker.dead_letter_queue.count(wid) == 1

        status, data = self._post(f"/dashboard/api/webhooks/{wid}/retry")
        assert status == 200
        assert data["replayed"] == 1
        assert data["webhook_id"] == wid

    def test_health_requires_dashboard_auth(self):
        wid = self.test_reg.webhook_id
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", f"/dashboard/api/webhooks/{wid}/health")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 401
