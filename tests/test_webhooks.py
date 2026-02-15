"""
Tests for UPAI Webhooks — signing, verification, delivery.

Covers:
- Sign/verify round-trip
- Tampered payload rejected
- Delivery to test HTTP server
- All headers present
- Webhook registration
"""

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from cortex.upai.webhooks import (
    WebhookRegistration, create_webhook, sign_payload,
    verify_webhook_signature, deliver_webhook, VALID_EVENTS,
)


# ============================================================================
# Sign / Verify
# ============================================================================

class TestWebhookSigning:

    def test_sign_payload(self):
        payload = b'{"event": "test"}'
        secret = "test-secret-key"
        sig = sign_payload(payload, secret)
        assert sig.startswith("sha256=")
        assert len(sig) > 10

    def test_verify_valid(self):
        payload = b'{"event": "test"}'
        secret = "test-secret"
        sig = sign_payload(payload, secret)
        assert verify_webhook_signature(payload, sig, secret)

    def test_verify_tampered(self):
        payload = b'{"event": "test"}'
        secret = "test-secret"
        sig = sign_payload(payload, secret)
        # Tamper with payload
        assert not verify_webhook_signature(b'{"event": "tampered"}', sig, secret)

    def test_verify_wrong_secret(self):
        payload = b'{"event": "test"}'
        sig = sign_payload(payload, "secret1")
        assert not verify_webhook_signature(payload, sig, "secret2")

    def test_verify_bad_format(self):
        assert not verify_webhook_signature(b"test", "not-sha256=abc", "secret")

    def test_sign_deterministic(self):
        payload = b"deterministic"
        secret = "key"
        sig1 = sign_payload(payload, secret)
        sig2 = sign_payload(payload, secret)
        assert sig1 == sig2


# ============================================================================
# Registration
# ============================================================================

class TestWebhookRegistration:

    def test_create_webhook(self):
        reg = create_webhook("https://example.com/hook", ["context.updated"])
        assert reg.webhook_id
        assert reg.url == "https://example.com/hook"
        assert reg.events == ["context.updated"]
        assert len(reg.secret) == 64  # hex-encoded 32 bytes
        assert reg.active is True
        assert reg.created_at

    def test_unique_ids(self):
        regs = [create_webhook("https://example.com", ["context.updated"]) for _ in range(5)]
        ids = {r.webhook_id for r in regs}
        assert len(ids) == 5

    def test_unique_secrets(self):
        regs = [create_webhook("https://example.com", ["context.updated"]) for _ in range(5)]
        secs = {r.secret for r in regs}
        assert len(secs) == 5

    def test_to_dict_from_dict(self):
        reg = create_webhook("https://example.com/hook", ["context.updated", "version.created"])
        d = reg.to_dict()
        restored = WebhookRegistration.from_dict(d)
        assert restored.webhook_id == reg.webhook_id
        assert restored.url == reg.url
        assert restored.events == reg.events
        assert restored.secret == reg.secret

    def test_valid_events_constant(self):
        assert "context.updated" in VALID_EVENTS
        assert "version.created" in VALID_EVENTS
        assert "grant.created" in VALID_EVENTS
        assert "grant.revoked" in VALID_EVENTS
        assert "key.rotated" in VALID_EVENTS


# ============================================================================
# Delivery to test server
# ============================================================================

class _WebhookTestHandler(BaseHTTPRequestHandler):
    """Test handler that captures webhook deliveries."""

    received_events: list[dict] = []
    received_headers: list[dict] = []

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)

        self.__class__.received_events.append(data)
        self.__class__.received_headers.append({
            "X-UPAI-Event": self.headers.get("X-UPAI-Event", ""),
            "X-UPAI-Signature": self.headers.get("X-UPAI-Signature", ""),
            "X-UPAI-Delivery": self.headers.get("X-UPAI-Delivery", ""),
            "X-UPAI-Timestamp": self.headers.get("X-UPAI-Timestamp", ""),
            "Content-Type": self.headers.get("Content-Type", ""),
        })

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


class TestWebhookDelivery:

    def test_deliver_to_server(self):
        _WebhookTestHandler.received_events = []
        _WebhookTestHandler.received_headers = []

        server = HTTPServer(("127.0.0.1", 0), _WebhookTestHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)

        try:
            reg = create_webhook(f"http://127.0.0.1:{port}/webhook", ["context.updated"])
            success, status = deliver_webhook(reg, "context.updated", {"key": "value"})

            assert success
            assert status == 200
            assert len(_WebhookTestHandler.received_events) == 1
            assert _WebhookTestHandler.received_events[0]["event"] == "context.updated"
        finally:
            server.shutdown()

    def test_delivery_headers_present(self):
        _WebhookTestHandler.received_events = []
        _WebhookTestHandler.received_headers = []

        server = HTTPServer(("127.0.0.1", 0), _WebhookTestHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)

        try:
            reg = create_webhook(f"http://127.0.0.1:{port}/webhook", ["version.created"])
            deliver_webhook(reg, "version.created", {"version": "v1"})

            headers = _WebhookTestHandler.received_headers[0]
            assert headers["X-UPAI-Event"] == "version.created"
            assert headers["X-UPAI-Signature"].startswith("sha256=")
            assert headers["X-UPAI-Delivery"]  # non-empty
            assert headers["X-UPAI-Timestamp"]  # non-empty
            assert headers["Content-Type"] == "application/json"
        finally:
            server.shutdown()

    def test_delivery_signature_valid(self):
        _WebhookTestHandler.received_events = []
        _WebhookTestHandler.received_headers = []

        server = HTTPServer(("127.0.0.1", 0), _WebhookTestHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)

        try:
            reg = create_webhook(f"http://127.0.0.1:{port}/webhook", ["context.updated"])
            deliver_webhook(reg, "context.updated", {"test": True})

            headers = _WebhookTestHandler.received_headers[0]
            sig = headers["X-UPAI-Signature"]

            # Re-construct payload and verify
            event_data = _WebhookTestHandler.received_events[0]
            payload = json.dumps(event_data).encode("utf-8")
            assert verify_webhook_signature(payload, sig, reg.secret)
        finally:
            server.shutdown()

    def test_deliver_connection_error(self):
        reg = create_webhook("http://127.0.0.1:1/nonexistent", ["context.updated"])
        success, status = deliver_webhook(reg, "context.updated", {}, timeout=1.0)
        assert not success
        assert status == 0
