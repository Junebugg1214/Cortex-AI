"""Tests for cortex.caas.sse — Server-Sent Events."""

import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from cortex.caas.sse import SSEManager
from cortex.upai.identity import UPAIIdentity, has_crypto


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


class TestSSEManager(unittest.TestCase):
    """Test SSEManager subscribe/unsubscribe/broadcast."""

    def test_subscribe_adds_subscriber(self):
        mgr = SSEManager()
        wfile = MockWfile()
        sub = mgr.subscribe(wfile, events={"test.event"})
        self.assertEqual(mgr.subscriber_count, 1)
        self.assertTrue(sub.alive)

    def test_unsubscribe_removes(self):
        mgr = SSEManager()
        wfile = MockWfile()
        sub = mgr.subscribe(wfile)
        mgr.unsubscribe(sub.subscriber_id)
        self.assertEqual(mgr.subscriber_count, 0)
        self.assertFalse(sub.alive)

    def test_broadcast_sends_to_matching(self):
        mgr = SSEManager()
        wfile1 = MockWfile()
        wfile2 = MockWfile()
        mgr.subscribe(wfile1, events={"context.updated"})
        mgr.subscribe(wfile2, events={"grant.created"})

        count = mgr.broadcast("context.updated", {"test": True})
        self.assertEqual(count, 1)

        output = wfile1.getvalue().decode()
        self.assertIn("event: context.updated", output)
        self.assertIn("data:", output)

        # wfile2 should NOT have received the event
        self.assertEqual(wfile2.getvalue(), b"")

    def test_broadcast_sends_to_all_when_empty_filter(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())  # Subscribe to all

        count = mgr.broadcast("any.event", {"data": 1})
        self.assertEqual(count, 1)
        output = wfile.getvalue().decode()
        self.assertIn("event: any.event", output)

    def test_dead_connection_auto_removed(self):
        mgr = SSEManager()
        wfile = MockWfile(fail_after=0)  # Fail immediately
        mgr.subscribe(wfile, events=set())

        count = mgr.broadcast("test", {})
        self.assertEqual(count, 0)
        self.assertEqual(mgr.subscriber_count, 0)

    def test_multiple_broadcasts(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())

        mgr.broadcast("event.a", {"a": 1})
        mgr.broadcast("event.b", {"b": 2})

        output = wfile.getvalue().decode()
        self.assertIn("event: event.a", output)
        self.assertIn("event: event.b", output)

    def test_shutdown_clears_all(self):
        mgr = SSEManager()
        wfile = MockWfile()
        sub = mgr.subscribe(wfile)
        mgr.shutdown()
        self.assertEqual(mgr.subscriber_count, 0)
        self.assertFalse(sub.alive)


class TestSSEFormat(unittest.TestCase):
    """Test SSE wire format compliance."""

    def test_event_data_format(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())

        mgr.broadcast("test.event", {"key": "value"})
        output = wfile.getvalue().decode()

        lines = output.strip().split("\n")
        # Wire format: id: N\nevent: ...\ndata: ...\n\n
        self.assertTrue(lines[0].startswith("id: "))
        self.assertTrue(lines[1].startswith("event: "))
        self.assertTrue(lines[2].startswith("data: "))
        # Should end with double newline (blank line separator)
        self.assertTrue(output.endswith("\n\n"))

    def test_data_is_valid_json(self):
        mgr = SSEManager()
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())

        mgr.broadcast("test", {"number": 42, "text": "hello"})
        output = wfile.getvalue().decode()

        for line in output.strip().split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                self.assertEqual(data["number"], 42)
                self.assertEqual(data["text"], "hello")


class TestSSEHeartbeat(unittest.TestCase):
    """Test SSE heartbeat mechanism."""

    def test_heartbeat_thread_sends_comments(self):
        mgr = SSEManager(heartbeat_interval=0.1)  # Fast heartbeat for testing
        wfile = MockWfile()
        mgr.subscribe(wfile, events=set())
        mgr.start()

        # Wait for at least one heartbeat
        time.sleep(0.3)
        mgr.shutdown()

        output = wfile.getvalue().decode()
        self.assertIn(":heartbeat", output)

    def test_heartbeat_removes_dead_connections(self):
        mgr = SSEManager(heartbeat_interval=0.1)
        wfile = MockWfile(fail_after=0)
        mgr.subscribe(wfile, events=set())
        mgr.start()

        time.sleep(0.3)
        mgr.shutdown()

        self.assertEqual(mgr.subscriber_count, 0)


# ── Integration tests for SSE route ──────────────────────────────────


def _setup_server(enable_sse=True):
    if not has_crypto():
        return None, None, None, None

    from cortex.caas.dashboard.auth import DashboardSessionManager
    from cortex.caas.server import CaaSHandler, JsonGrantStore, NonceCache, ThreadingHTTPServer
    from cortex.caas.storage import JsonWebhookStore
    from cortex.graph import CortexGraph
    from cortex.upai.credentials import CredentialStore
    from cortex.upai.disclosure import PolicyRegistry
    from cortex.upai.tokens import GrantToken

    identity = UPAIIdentity.generate("SSE Test")
    graph = CortexGraph()

    CaaSHandler.identity = identity
    CaaSHandler.graph = graph
    CaaSHandler.grant_store = JsonGrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.policy_registry = PolicyRegistry()
    CaaSHandler.session_manager = DashboardSessionManager(identity)
    CaaSHandler.audit_log = None
    CaaSHandler.webhook_worker = None
    CaaSHandler.metrics_registry = None
    CaaSHandler.rate_limiter = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = CredentialStore()
    CaaSHandler.keychain = None

    if enable_sse:
        sse = SSEManager(heartbeat_interval=30)
        sse.start()
        CaaSHandler.sse_manager = sse
    else:
        CaaSHandler.sse_manager = None

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Create token with context:subscribe scope
    token = GrantToken.create(identity, audience="sse-test",
                               scopes=["context:read", "context:subscribe"])
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestSSEAuth(unittest.TestCase):
    """Test SSE endpoint authentication."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.token = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            sse = cls.server.RequestHandlerClass.sse_manager
            if sse:
                sse.shutdown()
            cls.server.shutdown()

    def test_missing_token_401(self):
        try:
            url = f"http://127.0.0.1:{self.port}/events"
            req = urllib.request.Request(url)
            urllib.request.urlopen(req, timeout=2)
            self.fail("Expected 401")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_missing_subscribe_scope_403(self):
        from cortex.upai.tokens import GrantToken
        # Token without context:subscribe
        token = GrantToken.create(self.identity, audience="test", scopes=["context:read"])
        token_str = token.sign(self.identity)
        self.server.RequestHandlerClass.grant_store.add(token.grant_id, token_str, token.to_dict())

        try:
            url = f"http://127.0.0.1:{self.port}/events"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token_str}")
            urllib.request.urlopen(req, timeout=2)
            self.fail("Expected 403")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestSSEDisabled(unittest.TestCase):
    """Test SSE when disabled."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.token = _setup_server(enable_sse=False)

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()

    def test_returns_503(self):
        try:
            url = f"http://127.0.0.1:{self.port}/events"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {self.token}")
            urllib.request.urlopen(req, timeout=2)
            self.fail("Expected 503")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 503)


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestSSERoute(unittest.TestCase):
    """Test SSE route connection and event delivery."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port, cls.identity, cls.token = _setup_server()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            sse = cls.server.RequestHandlerClass.sse_manager
            if sse:
                sse.shutdown()
            cls.server.shutdown()

    def test_connect_and_receive_event(self):
        """Connect to /events and verify we can receive a broadcasted event."""
        import socket

        # Connect via raw socket to read SSE stream
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(("127.0.0.1", self.port))

        # Send HTTP request
        request = (
            f"GET /events?events=test.broadcast HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            f"Authorization: Bearer {self.token}\r\n"
            f"Accept: text/event-stream\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode())

        # Read response headers
        time.sleep(0.2)
        data = b""
        try:
            data = sock.recv(4096)
        except socket.timeout:
            pass

        response_text = data.decode("utf-8", errors="replace")
        self.assertIn("200", response_text)
        self.assertIn("text/event-stream", response_text)

        # Broadcast an event
        sse = self.server.RequestHandlerClass.sse_manager
        sse.broadcast("test.broadcast", {"msg": "hello"})

        time.sleep(0.3)
        try:
            more_data = sock.recv(4096)
            response_text += more_data.decode("utf-8", errors="replace")
        except socket.timeout:
            pass

        sock.close()

        self.assertIn("event: test.broadcast", response_text)
        self.assertIn("hello", response_text)


if __name__ == "__main__":
    unittest.main()
