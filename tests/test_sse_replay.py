"""
Tests for WP-5.5: SSE Event Replay & Buffering.

Covers:
- EventBuffer: append returns monotonic ID, since returns newer, ring buffer
  evicts, TTL cleanup, thread safety
- SSE event IDs: broadcast includes id, IDs are monotonic, id in wire format
- SSE replay: replay sends buffered, replay then live, expired ID = best effort,
  empty buffer
- Last-Event-ID parsing: header, query param, invalid ID ignored
"""

from __future__ import annotations

import io
import json
import socket
import threading
import time
import unittest

from cortex.caas.event_buffer import EventBuffer
from cortex.caas.sse import SSEManager
from cortex.upai.identity import UPAIIdentity, has_crypto

# ── Mock wfile ──────────────────────────────────────────────────────────


class MockWfile:
    """Mock socket write file for testing SSE output."""

    def __init__(self, fail_after=None):
        self._data = io.BytesIO()
        self._lock = threading.Lock()
        self._write_count = 0
        self._fail_after = fail_after

    def write(self, data):
        with self._lock:
            if self._fail_after is not None and self._write_count >= self._fail_after:
                raise BrokenPipeError("Mock connection closed")
            self._data.write(data)
            self._write_count += 1

    def flush(self):
        pass

    def getvalue(self):
        with self._lock:
            return self._data.getvalue()


# ── EventBuffer ─────────────────────────────────────────────────────────


class TestEventBuffer:
    def test_append_returns_monotonic_id(self):
        buf = EventBuffer()
        id1 = buf.append("ev.a", '{"a": 1}')
        id2 = buf.append("ev.b", '{"b": 2}')
        id3 = buf.append("ev.c", '{"c": 3}')
        assert id1 < id2 < id3

    def test_first_id_is_one(self):
        buf = EventBuffer()
        assert buf.append("ev", "{}") == 1

    def test_since_returns_newer(self):
        buf = EventBuffer()
        id1 = buf.append("ev.a", '{"a": 1}')
        id2 = buf.append("ev.b", '{"b": 2}')
        id3 = buf.append("ev.c", '{"c": 3}')

        events = buf.since(id1)
        assert len(events) == 2
        assert events[0].event_id == id2
        assert events[1].event_id == id3

    def test_since_zero_returns_all(self):
        buf = EventBuffer()
        buf.append("ev.a", "{}")
        buf.append("ev.b", "{}")
        events = buf.since(0)
        assert len(events) == 2

    def test_since_latest_returns_empty(self):
        buf = EventBuffer()
        last = buf.append("ev", "{}")
        events = buf.since(last)
        assert len(events) == 0

    def test_ring_buffer_evicts(self):
        buf = EventBuffer(max_size=5)
        for i in range(10):
            buf.append(f"ev.{i}", "{}")
        assert buf.count() == 5
        events = buf.since(0)
        # Should have events 6-10 (IDs 6, 7, 8, 9, 10)
        assert events[0].event_id == 6
        assert len(events) == 5

    def test_ttl_cleanup(self):
        buf = EventBuffer(max_size=100, ttl_seconds=0.1)
        buf.append("old", "{}")
        time.sleep(0.15)
        buf.append("new", "{}")

        events = buf.since(0)
        assert len(events) == 1
        assert events[0].event_type == "new"

    def test_latest_id(self):
        buf = EventBuffer()
        assert buf.latest_id() == 0
        buf.append("ev", "{}")
        assert buf.latest_id() == 1
        buf.append("ev", "{}")
        assert buf.latest_id() == 2

    def test_count(self):
        buf = EventBuffer()
        assert buf.count() == 0
        buf.append("ev", "{}")
        buf.append("ev", "{}")
        assert buf.count() == 2

    def test_max_size_property(self):
        buf = EventBuffer(max_size=500)
        assert buf.max_size == 500

    def test_thread_safety(self):
        buf = EventBuffer(max_size=1000)
        errors = []

        def append_many():
            try:
                for i in range(100):
                    buf.append(f"ev.{i}", "{}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=append_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert buf.count() == 400

    def test_buffered_event_fields(self):
        buf = EventBuffer()
        eid = buf.append("context.updated", '{"nodes": [1]}')
        events = buf.since(0)
        assert len(events) == 1
        ev = events[0]
        assert ev.event_id == eid
        assert ev.event_type == "context.updated"
        assert ev.data == '{"nodes": [1]}'
        assert ev.timestamp > 0


# ── SSE Event IDs ──────────────────────────────────────────────────────


class TestSSEEventIds:
    def test_broadcast_includes_id_in_output(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())

        mgr.broadcast("test.event", {"key": "val"})
        output = wfile.getvalue().decode()

        assert "id: " in output
        assert "event: test.event" in output
        assert "data: " in output

    def test_ids_are_monotonic(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())

        mgr.broadcast("ev.a", {})
        mgr.broadcast("ev.b", {})
        mgr.broadcast("ev.c", {})

        output = wfile.getvalue().decode()
        # Extract IDs
        ids = []
        for line in output.split("\n"):
            if line.startswith("id: "):
                ids.append(int(line[4:]))
        assert len(ids) == 3
        assert ids[0] < ids[1] < ids[2]

    def test_id_in_wire_format(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())

        mgr.broadcast("test.event", {"data": 1})
        output = wfile.getvalue().decode()

        # SSE format: id: N\nevent: ...\ndata: ...\n\n
        lines = output.strip().split("\n")
        assert lines[0].startswith("id: ")
        assert lines[1].startswith("event: ")
        assert lines[2].startswith("data: ")

    def test_events_buffered_for_replay(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())

        mgr.broadcast("ev.a", {"a": 1})
        mgr.broadcast("ev.b", {"b": 2})

        # Buffer should have both events
        assert mgr.event_buffer.count() == 2


# ── SSE Replay ──────────────────────────────────────────────────────────


class TestSSEReplay:
    def test_replay_sends_buffered(self):
        mgr = SSEManager()
        # Broadcast without any subscribers
        mgr.broadcast("ev.a", {"a": 1})
        mgr.broadcast("ev.b", {"b": 2})
        mgr.broadcast("ev.c", {"c": 3})

        # Replay to a new wfile
        wfile = MockWfile()
        count = mgr.replay(wfile, since_id=0)
        assert count == 3

        output = wfile.getvalue().decode()
        assert "event: ev.a" in output
        assert "event: ev.b" in output
        assert "event: ev.c" in output
        # IDs should be present
        assert "id: " in output

    def test_replay_only_since_id(self):
        mgr = SSEManager()
        id1 = mgr.event_buffer.append("ev.a", '{"a": 1}')
        mgr.event_buffer.append("ev.b", '{"b": 2}')
        mgr.event_buffer.append("ev.c", '{"c": 3}')

        wfile = MockWfile()
        count = mgr.replay(wfile, since_id=id1)
        assert count == 2

        output = wfile.getvalue().decode()
        assert "event: ev.a" not in output
        assert "event: ev.b" in output
        assert "event: ev.c" in output

    def test_replay_with_event_filter(self):
        mgr = SSEManager()
        mgr.broadcast("ev.a", {})
        mgr.broadcast("ev.b", {})
        mgr.broadcast("ev.a", {})

        wfile = MockWfile()
        count = mgr.replay(wfile, since_id=0, events={"ev.a"})
        assert count == 2

        output = wfile.getvalue().decode()
        assert "event: ev.b" not in output
        assert output.count("event: ev.a") == 2

    def test_replay_empty_buffer(self):
        mgr = SSEManager()
        wfile = MockWfile()
        count = mgr.replay(wfile, since_id=0)
        assert count == 0
        assert wfile.getvalue() == b""

    def test_replay_expired_id_returns_available(self):
        mgr = SSEManager(buffer_size=3)
        # Fill and evict
        mgr.broadcast("ev.1", {})
        mgr.broadcast("ev.2", {})
        mgr.broadcast("ev.3", {})
        mgr.broadcast("ev.4", {})
        mgr.broadcast("ev.5", {})

        # Asking for ID 1 which was evicted — should get whatever is available
        wfile = MockWfile()
        count = mgr.replay(wfile, since_id=1)
        assert count == 3  # IDs 3, 4, 5 remain

    def test_replay_then_live(self):
        mgr = SSEManager()
        # Buffer some events
        mgr.broadcast("ev.old", {"old": True})

        # New subscriber connects with replay
        wfile = MockWfile()
        count = mgr.replay(wfile, since_id=0)
        assert count == 1

        # Subscribe for live events
        mgr.subscribe(wfile, events=set())
        mgr.broadcast("ev.new", {"new": True})

        output = wfile.getvalue().decode()
        assert "event: ev.old" in output
        assert "event: ev.new" in output

    def test_replay_stops_on_broken_pipe(self):
        mgr = SSEManager()
        for i in range(5):
            mgr.broadcast(f"ev.{i}", {})

        wfile = MockWfile(fail_after=2)  # Will fail after 2 writes
        count = mgr.replay(wfile, since_id=0)
        assert count < 5


# ── Last-Event-ID parsing (server integration) ──────────────────────────


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestLastEventIdParsing(unittest.TestCase):
    """Test Last-Event-ID header and query param in /events endpoint."""

    @classmethod
    def setUpClass(cls):
        from cortex.caas.dashboard.auth import DashboardSessionManager
        from cortex.caas.server import CaaSHandler, JsonGrantStore, NonceCache, ThreadingHTTPServer
        from cortex.caas.storage import JsonWebhookStore
        from cortex.graph import CortexGraph
        from cortex.upai.disclosure import PolicyRegistry
        from cortex.upai.tokens import GrantToken

        cls.identity = UPAIIdentity.generate("SSE Replay Test")
        graph = CortexGraph()

        CaaSHandler.identity = cls.identity
        CaaSHandler.graph = graph
        CaaSHandler.grant_store = JsonGrantStore()
        CaaSHandler.nonce_cache = NonceCache()
        CaaSHandler.webhook_store = JsonWebhookStore()
        CaaSHandler.policy_registry = PolicyRegistry()
        CaaSHandler.session_manager = DashboardSessionManager(cls.identity)
        CaaSHandler.audit_log = None
        CaaSHandler.webhook_worker = None
        CaaSHandler.metrics_registry = None
        CaaSHandler.rate_limiter = None
        CaaSHandler.oauth_manager = None
        CaaSHandler.credential_store = None
        CaaSHandler.keychain = None
        CaaSHandler.version_store = None

        cls.sse = SSEManager(heartbeat_interval=30)
        cls.sse.start()
        CaaSHandler.sse_manager = cls.sse

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
        cls.port = cls.server.server_address[1]
        CaaSHandler._allowed_origins = {f"http://127.0.0.1:{cls.port}"}

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        # Create token with subscribe scope
        token = GrantToken.create(cls.identity, audience="sse-replay",
                                   scopes=["context:read", "context:subscribe"])
        cls.token_str = token.sign(cls.identity)
        CaaSHandler.grant_store.add(token.grant_id, cls.token_str, token.to_dict())

        # Pre-broadcast some events for replay
        cls.sse.broadcast("ev.pre1", {"seq": 1})
        cls.sse.broadcast("ev.pre2", {"seq": 2})
        cls.sse.broadcast("ev.pre3", {"seq": 3})

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'sse') and cls.sse:
            cls.sse.shutdown()
        if hasattr(cls, 'server') and cls.server:
            cls.server.shutdown()

    def _connect_sse(self, extra_headers="", query_params=""):
        """Connect to SSE endpoint via raw socket, return received data."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(("127.0.0.1", self.port))

        path = f"/events{query_params}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            f"Authorization: Bearer {self.token_str}\r\n"
            f"Accept: text/event-stream\r\n"
            f"{extra_headers}"
            f"\r\n"
        )
        sock.sendall(request.encode())
        time.sleep(0.5)

        data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        finally:
            sock.close()

        return data.decode("utf-8", errors="replace")

    def test_last_event_id_header_triggers_replay(self):
        response = self._connect_sse(
            extra_headers="Last-Event-ID: 1\r\n"
        )
        self.assertIn("200", response)
        # Should replay events with ID > 1 (i.e., pre2 and pre3)
        self.assertIn("event: ev.pre2", response)
        self.assertIn("event: ev.pre3", response)

    def test_last_event_id_query_param(self):
        response = self._connect_sse(query_params="?last_event_id=2")
        self.assertIn("200", response)
        # Should replay events with ID > 2 (i.e., pre3)
        self.assertIn("event: ev.pre3", response)

    def test_no_last_event_id_no_replay(self):
        response = self._connect_sse()
        self.assertIn("200", response)
        # Without Last-Event-ID, no replay events — just the live stream
        # Pre-events were broadcast before this subscriber connected
        # They should NOT appear in the response (no replay without Last-Event-ID)
        # The response should just have headers, no event data yet
        self.assertNotIn("event: ev.pre1", response)

    def test_invalid_last_event_id_ignored(self):
        response = self._connect_sse(
            extra_headers="Last-Event-ID: not-a-number\r\n"
        )
        self.assertIn("200", response)
        # Invalid ID treated as 0 but we only replay when > 0
        # So no replay should happen


# ── Backward compatibility with existing SSE tests ──────────────────────


class TestSSEBackwardCompat:
    """Verify existing SSE behavior still works after event buffer integration."""

    def test_subscribe_and_broadcast(self):
        mgr = SSEManager()
        wfile = MockWfile()
        sub = mgr.subscribe(wfile, events={"test.event"})
        assert mgr.subscriber_count == 1
        assert sub.alive

        count = mgr.broadcast("test.event", {"key": "val"})
        assert count == 1

        output = wfile.getvalue().decode()
        assert "event: test.event" in output
        assert "data:" in output

    def test_unsubscribe(self):
        mgr = SSEManager()
        wfile = MockWfile()
        sub = mgr.subscribe(wfile)
        mgr.unsubscribe(sub.subscriber_id)
        assert mgr.subscriber_count == 0
        assert not sub.alive

    def test_event_filter(self):
        mgr = SSEManager()
        wfile1 = MockWfile()
        wfile2 = MockWfile()
        mgr.subscribe(wfile1, events={"context.updated"})
        mgr.subscribe(wfile2, events={"grant.created"})

        mgr.broadcast("context.updated", {})
        assert wfile1.getvalue() != b""
        assert wfile2.getvalue() == b""

    def test_dead_connection_removed(self):
        mgr = SSEManager()
        wfile = MockWfile(fail_after=0)
        mgr.subscribe(wfile, events=set())
        count = mgr.broadcast("test", {})
        assert count == 0
        assert mgr.subscriber_count == 0

    def test_shutdown_clears(self):
        mgr = SSEManager()
        wfile = MockWfile()
        sub = mgr.subscribe(wfile)
        mgr.shutdown()
        assert mgr.subscriber_count == 0
        assert not sub.alive

    def test_data_is_valid_json(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())
        mgr.broadcast("test", {"number": 42})

        output = wfile.getvalue().decode()
        for line in output.strip().split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                assert data["number"] == 42
