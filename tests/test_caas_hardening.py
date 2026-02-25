"""
Tests for CaaS server hardening — rate limiting, input validation, health check, audit.

Uses the same server setup pattern as test_caas_server.py.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer

from cortex.caas.rate_limit import RateLimiter
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import InMemoryAuditLog, JsonWebhookStore
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import VALID_SCOPES, GrantToken


def _build_test_graph():
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="knows"))
    return g


def _setup_server(rate_limiter=None, audit_log=None):
    if not has_crypto():
        return None, None, None, None

    identity = UPAIIdentity.generate("Test User")
    graph = _build_test_graph()

    from cortex.upai.disclosure import PolicyRegistry

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.audit_log = audit_log
    CaaSHandler.rate_limiter = rate_limiter
    CaaSHandler.webhook_worker = None
    CaaSHandler.metrics_registry = None
    CaaSHandler.session_manager = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = None
    CaaSHandler.sse_manager = None
    CaaSHandler.keychain = None
    CaaSHandler.policy_registry = PolicyRegistry()
    CaaSHandler._allowed_origins = set()

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    token = GrantToken.create(identity, audience="Test", scopes=list(VALID_SCOPES))
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


def _get(port, path, token=None, expect_error=False):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        if expect_error:
            return json.loads(e.read()), e.code
        raise


def _post(port, path, data, token=None, expect_error=False, raw_body=None):
    url = f"http://127.0.0.1:{port}{path}"
    if raw_body is not None:
        body = raw_body
    else:
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        if expect_error:
            return json.loads(e.read()), e.code
        raise


# ============================================================================
# Health check
# ============================================================================

class TestHealthCheck:

    def test_health_returns_200(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/health")
            assert status == 200
            assert data["status"] == "ok"
            assert data["version"] == "1.4.0"
            assert data["has_identity"] is True
            assert data["has_graph"] is True
            assert isinstance(data["grant_count"], int)
        finally:
            server.shutdown()

    def test_health_no_auth_required(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            # No token — should still work
            data, status = _get(port, "/health")
            assert status == 200
        finally:
            server.shutdown()


# ============================================================================
# Rate limiting
# ============================================================================

class TestRateLimiter:

    def test_allows_normal_traffic(self):
        limiter = RateLimiter(max_requests=10, window=60)
        for _ in range(10):
            assert limiter.allow("127.0.0.1") is True

    def test_blocks_burst(self):
        limiter = RateLimiter(max_requests=5, window=60)
        for _ in range(5):
            assert limiter.allow("127.0.0.1") is True
        assert limiter.allow("127.0.0.1") is False

    def test_different_ips_independent(self):
        limiter = RateLimiter(max_requests=2, window=60)
        assert limiter.allow("1.1.1.1") is True
        assert limiter.allow("1.1.1.1") is True
        assert limiter.allow("1.1.1.1") is False
        # Different IP still works
        assert limiter.allow("2.2.2.2") is True

    def test_cleanup(self):
        import time as _time
        limiter = RateLimiter(max_requests=5, window=1)
        limiter._requests["old"] = [_time.monotonic() - 10]  # clearly expired
        limiter.cleanup()
        assert "old" not in limiter._requests


class TestRateLimitIntegration:

    def test_server_returns_429(self):
        limiter = RateLimiter(max_requests=2, window=60)
        server, port, identity, token_str = _setup_server(rate_limiter=limiter)
        if server is None:
            return
        try:
            _get(port, "/health")
            _get(port, "/health")
            data, status = _get(port, "/health", expect_error=True)
            assert status == 429
            assert data["error"]["type"] == "rate_limited"
        finally:
            CaaSHandler.rate_limiter = None
            CaaSHandler.login_rate_limiter = None
            server.shutdown()


# ============================================================================
# Input validation
# ============================================================================

class TestInputValidation:

    def test_body_size_limit(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            # Create a body larger than 1MB
            big_body = json.dumps({"audience": "x" * (1024 * 1024 + 100)}).encode("utf-8")
            try:
                data, status = _post(port, "/grants", {}, token=token_str,
                                   expect_error=True, raw_body=big_body)
                assert status == 413
            except (urllib.error.URLError, ConnectionError, OSError):
                # Server may reset the connection before reading the full body —
                # this is acceptable behavior for oversized requests.
                pass
        finally:
            server.shutdown()

    def test_invalid_audience_too_long(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/grants",
                               {"audience": "x" * 257, "policy": "professional"},
                               token=token_str, expect_error=True)
            assert status == 400
            assert "256" in data["error"]["message"]
        finally:
            server.shutdown()

    def test_invalid_ttl_too_low(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/grants",
                               {"audience": "Test", "ttl_hours": 0},
                               token=token_str, expect_error=True)
            assert status == 400
            assert "ttl_hours" in data["error"]["message"]
        finally:
            server.shutdown()

    def test_invalid_ttl_too_high(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/grants",
                               {"audience": "Test", "ttl_hours": 9999},
                               token=token_str, expect_error=True)
            assert status == 400
        finally:
            server.shutdown()

    def test_invalid_scope(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/grants",
                               {"audience": "Test", "scopes": ["bad:scope"]},
                               token=token_str, expect_error=True)
            assert status == 400
            assert "Unknown scope" in data["error"]["message"]
        finally:
            server.shutdown()

    def test_invalid_webhook_url_no_scheme(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/webhooks",
                               {"url": "not-a-url", "events": ["grant.created"]},
                               token=token_str, expect_error=True)
            assert status == 400
            assert "http" in data["error"]["message"]
        finally:
            server.shutdown()

    def test_invalid_webhook_url_too_long(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/webhooks",
                               {"url": "https://example.com/" + "x" * 2049},
                               token=token_str, expect_error=True)
            assert status == 400
            assert "2048" in data["error"]["message"]
        finally:
            server.shutdown()


# ============================================================================
# Audit logging
# ============================================================================

class TestAuditLogging:

    def test_audit_on_grant_created(self):
        audit = InMemoryAuditLog()
        server, port, identity, token_str = _setup_server(audit_log=audit)
        if server is None:
            return
        try:
            _post(port, "/grants",
                  {"audience": "AuditTest", "policy": "professional"},
                  token=token_str)
            entries = audit.query(event_type="grant.created")
            assert len(entries) >= 1
            assert entries[0]["details"]["audience"] == "AuditTest"
        finally:
            CaaSHandler.audit_log = None
            server.shutdown()

    def test_audit_on_grant_revoked(self):
        audit = InMemoryAuditLog()
        server, port, identity, token_str = _setup_server(audit_log=audit)
        if server is None:
            return
        try:
            # Create a grant first
            resp, _ = _post(port, "/grants",
                           {"audience": "RevokeTest", "policy": "professional"},
                           token=token_str)
            grant_id = resp["grant_id"]

            # Revoke it
            url = f"http://127.0.0.1:{port}/grants/{grant_id}"
            req = urllib.request.Request(url, method="DELETE")
            req.add_header("Authorization", f"Bearer {token_str}")
            urllib.request.urlopen(req)

            entries = audit.query(event_type="grant.revoked")
            assert len(entries) >= 1
            assert entries[0]["details"]["grant_id"] == grant_id
        finally:
            CaaSHandler.audit_log = None
            server.shutdown()

    def test_audit_on_auth_failed(self):
        audit = InMemoryAuditLog()
        server, port, identity, token_str = _setup_server(audit_log=audit)
        if server is None:
            return
        try:
            _get(port, "/context", token="bad-token", expect_error=True)
            entries = audit.query(event_type="auth.failed")
            assert len(entries) >= 1
        finally:
            CaaSHandler.audit_log = None
            server.shutdown()

    def test_audit_on_webhook_created(self):
        audit = InMemoryAuditLog()
        server, port, identity, token_str = _setup_server(audit_log=audit)
        if server is None:
            return
        try:
            _post(port, "/webhooks",
                  {"url": "https://example.com/hook", "events": ["grant.created"]},
                  token=token_str)
            entries = audit.query(event_type="webhook.created")
            assert len(entries) >= 1
        finally:
            CaaSHandler.audit_log = None
            server.shutdown()


# ============================================================================
# ERR_RATE_LIMITED error code
# ============================================================================

class TestErrorCodes:

    def test_rate_limited_error(self):
        from cortex.upai.errors import ERR_RATE_LIMITED, ERROR_CODES
        err = ERR_RATE_LIMITED()
        assert err.code == "UPAI-4009"
        assert err.http_status == 429
        assert "UPAI-4009" in ERROR_CODES
