"""
Tests for webhook delivery worker.

Uses a mock HTTP server to receive webhook deliveries.
"""

import json
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

from cortex.graph import CortexGraph, Node
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import GrantToken
from cortex.upai.webhooks import create_webhook
from cortex.caas.storage import JsonWebhookStore
from cortex.caas.webhook_worker import WebhookWorker
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache


# ---------------------------------------------------------------------------
# Mock HTTP server to receive webhooks
# ---------------------------------------------------------------------------

class _WebhookReceiver(BaseHTTPRequestHandler):
    """Mock server that records received webhooks."""
    received: list = []
    fail_count: int = 0  # Return 500 for this many requests before succeeding
    _request_count: int = 0

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body) if body else {}

        self.__class__._request_count += 1

        if self.__class__._request_count <= self.__class__.fail_count:
            self.send_response(500)
            self.end_headers()
            return

        self.__class__.received.append({
            "event": self.headers.get("X-UPAI-Event", ""),
            "signature": self.headers.get("X-UPAI-Signature", ""),
            "data": data,
        })
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _start_receiver():
    """Start a mock webhook receiver. Returns (server, port)."""
    _WebhookReceiver.received = []
    _WebhookReceiver.fail_count = 0
    _WebhookReceiver._request_count = 0
    server = HTTPServer(("127.0.0.1", 0), _WebhookReceiver)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ============================================================================
# WebhookWorker unit tests
# ============================================================================

class TestWebhookWorker:

    def test_delivers_to_matching_webhooks(self):
        receiver, recv_port = _start_receiver()
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{recv_port}/hook", ["grant.created"])
            store.add(reg)

            worker = WebhookWorker(store, max_retries=1, backoff_base=0.1)
            worker.start()
            worker.enqueue("grant.created", {"grant_id": "g1"})
            time.sleep(1.0)
            worker.stop()

            assert len(_WebhookReceiver.received) == 1
            assert _WebhookReceiver.received[0]["event"] == "grant.created"
            assert _WebhookReceiver.received[0]["data"]["data"]["grant_id"] == "g1"
        finally:
            receiver.shutdown()

    def test_skips_unsubscribed_events(self):
        receiver, recv_port = _start_receiver()
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{recv_port}/hook", ["grant.revoked"])
            store.add(reg)

            worker = WebhookWorker(store, max_retries=1, backoff_base=0.1)
            worker.start()
            worker.enqueue("grant.created", {"grant_id": "g1"})
            time.sleep(0.5)
            worker.stop()

            assert len(_WebhookReceiver.received) == 0
        finally:
            receiver.shutdown()

    def test_retries_on_failure(self):
        receiver, recv_port = _start_receiver()
        _WebhookReceiver.fail_count = 1  # Fail first request, succeed second
        try:
            store = JsonWebhookStore()
            reg = create_webhook(f"http://127.0.0.1:{recv_port}/hook", ["grant.created"])
            store.add(reg)

            worker = WebhookWorker(store, max_retries=3, backoff_base=0.1)
            worker.start()
            worker.enqueue("grant.created", {"grant_id": "g1"})
            time.sleep(2.0)
            worker.stop()

            assert len(_WebhookReceiver.received) == 1
        finally:
            receiver.shutdown()

    def test_stop_is_clean(self):
        store = JsonWebhookStore()
        worker = WebhookWorker(store, max_retries=1, backoff_base=0.1)
        worker.start()
        worker.stop()
        assert not worker._thread.is_alive()


# ============================================================================
# Integration: server fires webhooks
# ============================================================================

def _setup_caas_server():
    """Set up CaaS test server with webhook store."""
    if not has_crypto():
        return None, None, None, None, None

    identity = UPAIIdentity.generate("Test User")
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Test", tags=["identity"], confidence=0.9))

    store = JsonWebhookStore()
    worker = WebhookWorker(store, max_retries=1, backoff_base=0.1)
    worker.start()

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = store
    CaaSHandler.audit_log = None
    CaaSHandler.rate_limiter = None
    CaaSHandler.webhook_worker = worker
    CaaSHandler._allowed_origins = set()

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    token = GrantToken.create(identity, audience="Test")
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str, worker


class TestServerWebhookFiring:

    def test_fires_webhook_on_grant_create(self):
        receiver, recv_port = _start_receiver()
        server, port, identity, token_str, worker = _setup_caas_server()
        if server is None:
            receiver.shutdown()
            return
        try:
            # Register webhook
            reg = create_webhook(f"http://127.0.0.1:{recv_port}/hook", ["grant.created"])
            CaaSHandler.webhook_store.add(reg)

            # Create a grant
            url = f"http://127.0.0.1:{port}/grants"
            body = json.dumps({"audience": "HookTest", "policy": "professional"}).encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {token_str}")
            urllib.request.urlopen(req)

            time.sleep(1.0)

            assert len(_WebhookReceiver.received) >= 1
            assert _WebhookReceiver.received[0]["event"] == "grant.created"
        finally:
            worker.stop()
            CaaSHandler.webhook_worker = None
            server.shutdown()
            receiver.shutdown()

    def test_fires_webhook_on_grant_revoke(self):
        receiver, recv_port = _start_receiver()
        server, port, identity, token_str, worker = _setup_caas_server()
        if server is None:
            receiver.shutdown()
            return
        try:
            # Register webhook for revoke events
            reg = create_webhook(f"http://127.0.0.1:{recv_port}/hook", ["grant.revoked"])
            CaaSHandler.webhook_store.add(reg)

            # Create a grant first
            url = f"http://127.0.0.1:{port}/grants"
            body = json.dumps({"audience": "RevokeHook", "policy": "professional"}).encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {token_str}")
            resp = urllib.request.urlopen(req)
            grant_data = json.loads(resp.read())
            grant_id = grant_data["grant_id"]

            # Revoke
            url = f"http://127.0.0.1:{port}/grants/{grant_id}"
            req = urllib.request.Request(url, method="DELETE")
            urllib.request.urlopen(req)

            time.sleep(1.0)

            assert len(_WebhookReceiver.received) >= 1
            revoke_events = [r for r in _WebhookReceiver.received if r["event"] == "grant.revoked"]
            assert len(revoke_events) >= 1
        finally:
            worker.stop()
            CaaSHandler.webhook_worker = None
            server.shutdown()
            receiver.shutdown()
