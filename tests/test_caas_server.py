"""
Tests for CaaS HTTP API Server.

Follows tests/test_dashboard.py pattern:
- HTTPServer on random port + daemon thread
- urllib.request client
- Tests every endpoint, auth flow, error codes, pagination, CORS
"""

import json
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer

from cortex.graph import CortexGraph, Node, Edge
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import GrantToken, SCOPE_CONTEXT_READ, SCOPE_VERSIONS_READ
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache, ThreadingHTTPServer
from cortex.caas.storage import JsonWebhookStore


def _build_test_graph() -> CortexGraph:
    """Build a test graph with diverse nodes."""
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    g.add_node(Node(id="n3", label="CEO", tags=["professional_context"], confidence=0.85))
    g.add_node(Node(id="n4", label="Healthcare", tags=["domain_knowledge"], confidence=0.8))
    g.add_node(Node(id="n5", label="Ship fast", tags=["active_priorities"], confidence=0.75))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n3", relation="has_role"))
    g.add_edge(Edge(id="e2", source_id="n2", target_id="n4", relation="used_in"))
    return g


def _setup_server():
    """Set up test server with identity and graph. Returns (server, port, identity, token_str)."""
    if not has_crypto():
        return None, None, None, None

    identity = UPAIIdentity.generate("Test User")
    graph = _build_test_graph()

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler._allowed_origins = set()

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    # Create a grant token
    token = GrantToken.create(identity, audience="Test")
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


def _get(port, path, token=None, expect_error=False):
    """Helper to make GET request."""
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


def _post(port, path, data, token=None, expect_error=False):
    """Helper to make POST request."""
    url = f"http://127.0.0.1:{port}{path}"
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


def _delete(port, path, expect_error=False):
    """Helper to make DELETE request."""
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        if expect_error:
            return json.loads(e.read()), e.code
        raise


# ============================================================================
# Server info / Discovery (no auth)
# ============================================================================

class TestCaaSInfo:

    def test_server_info(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/")
            assert status == 200
            assert data["service"] == "UPAI Context-as-a-Service"
            assert data["version"] == "1.0.0"
            assert data["did"] == identity.did
        finally:
            server.shutdown()

    def test_discovery(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/.well-known/upai-configuration")
            assert status == 200
            assert data["upai_version"] == "1.0"
            assert data["did"] == identity.did
            assert "context" in data["endpoints"]
            assert "grants" in data["endpoints"]
            assert "professional" in data["supported_policies"]
        finally:
            server.shutdown()

    def test_identity_endpoint(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/identity")
            assert status == 200
            assert data["@context"] == "https://www.w3.org/ns/did/v1"
            assert data["id"] == identity.did
            assert "verificationMethod" in data
            # Service endpoint should reference CaaS
            assert "service" in data
            assert data["service"][0]["type"] == "ContextService"
        finally:
            server.shutdown()


# ============================================================================
# Grant flow
# ============================================================================

class TestCaaSGrants:

    def test_create_grant(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/grants", {
                "audience": "Claude",
                "policy": "professional",
            })
            assert status == 201
            assert "token" in data
            assert "grant_id" in data
            assert data["policy"] == "professional"
        finally:
            server.shutdown()

    def test_list_grants(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/grants")
            assert status == 200
            assert "grants" in data
            assert len(data["grants"]) >= 1  # at least the setup token
        finally:
            server.shutdown()

    def test_revoke_grant(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            # Create a new grant
            create_data, _ = _post(port, "/grants", {"audience": "RevTest"})
            grant_id = create_data["grant_id"]
            new_token = create_data["token"]

            # Revoke it
            data, status = _delete(port, f"/grants/{grant_id}")
            assert status == 200
            assert data["revoked"] is True

            # Try to use revoked token
            err_data, err_status = _get(port, "/context", token=new_token, expect_error=True)
            assert err_status == 401
        finally:
            server.shutdown()

    def test_create_grant_missing_audience(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/grants", {"policy": "full"}, expect_error=True)
            assert status == 400
        finally:
            server.shutdown()

    def test_create_grant_bad_policy(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _post(port, "/grants", {
                "audience": "Test", "policy": "nonexistent"
            }, expect_error=True)
            assert status == 400
        finally:
            server.shutdown()


# ============================================================================
# Context endpoints (require auth)
# ============================================================================

class TestCaaSContext:

    def test_context_requires_auth(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context", expect_error=True)
            assert status == 401
        finally:
            server.shutdown()

    def test_context_with_token(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context", token=token)
            assert status == 200
            assert "graph" in data
            assert "nodes" in data["graph"]
        finally:
            server.shutdown()

    def test_context_compact(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            url = f"http://127.0.0.1:{port}/context/compact"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token}")
            resp = urllib.request.urlopen(req)
            body = resp.read().decode("utf-8")
            assert "Marc" in body or "Python" in body
        finally:
            server.shutdown()

    def test_context_nodes_paginated(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context/nodes?limit=2", token=token)
            assert status == 200
            assert "items" in data
            assert len(data["items"]) <= 2
            assert "has_more" in data
        finally:
            server.shutdown()

    def test_context_single_node(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context/nodes/n1", token=token)
            assert status == 200
            assert data["id"] == "n1"
            assert data["label"] == "Marc"
        finally:
            server.shutdown()

    def test_context_node_not_found(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context/nodes/nonexistent", token=token, expect_error=True)
            assert status == 404
        finally:
            server.shutdown()

    def test_context_edges(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context/edges", token=token)
            assert status == 200
            assert "items" in data
        finally:
            server.shutdown()

    def test_context_stats(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context/stats", token=token)
            assert status == 200
            assert "node_count" in data
            assert "edge_count" in data
        finally:
            server.shutdown()


# ============================================================================
# Auth edge cases
# ============================================================================

class TestCaaSAuth:

    def test_invalid_token(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context", token="invalid.token.here", expect_error=True)
            assert status == 401
        finally:
            server.shutdown()

    def test_missing_auth_header(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context", expect_error=True)
            assert status == 401
        finally:
            server.shutdown()

    def test_insufficient_scope(self):
        server, port, identity, token_str = _setup_server()
        if server is None:
            return
        try:
            # Create token with only context:read scope
            t = GrantToken.create(identity, "Test", scopes=["context:read"])
            ts = t.sign(identity)
            CaaSHandler.grant_store.add(t.grant_id, ts, t.to_dict())

            # Try to access versions (requires versions:read)
            data, status = _get(port, "/versions", token=ts, expect_error=True)
            assert status == 403
        finally:
            server.shutdown()


# ============================================================================
# Error codes
# ============================================================================

class TestCaaSErrorCodes:

    def test_404_unknown_endpoint(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/nonexistent", expect_error=True)
            assert status == 404
            assert "error" in data
            assert data["error"]["code"] == "UPAI-4003"
        finally:
            server.shutdown()

    def test_error_structure(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, status = _get(port, "/context", expect_error=True)
            assert "error" in data
            error = data["error"]
            assert "code" in error
            assert "type" in error
            assert "message" in error
        finally:
            server.shutdown()


# ============================================================================
# Security headers
# ============================================================================

class TestCaaSSecurity:

    def test_security_headers(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            url = f"http://127.0.0.1:{port}/"
            resp = urllib.request.urlopen(url)
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("X-Frame-Options") == "DENY"
            assert "Content-Security-Policy" in resp.headers
        finally:
            server.shutdown()


# ============================================================================
# Pagination
# ============================================================================

class TestCaaSPagination:

    def test_cursor_pagination(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            # Get first page
            data1, _ = _get(port, "/context/nodes?limit=2", token=token)
            assert len(data1["items"]) == 2

            if data1["has_more"]:
                cursor = data1["cursor"]
                data2, _ = _get(port, f"/context/nodes?limit=2&cursor={cursor}", token=token)
                assert len(data2["items"]) > 0
                # IDs should not overlap
                ids1 = {i["id"] for i in data1["items"]}
                ids2 = {i["id"] for i in data2["items"]}
                assert ids1.isdisjoint(ids2)
        finally:
            server.shutdown()

    def test_limit_clamping(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            data, _ = _get(port, "/context/nodes?limit=1000", token=token)
            # limit is clamped to 100
            assert len(data["items"]) <= 100
        finally:
            server.shutdown()


# ============================================================================
# GrantStore unit tests
# ============================================================================

class TestGrantStore:

    def test_add_and_get(self):
        store = GrantStore()
        store.add("g1", "token_string", {"audience": "Test", "issued_at": "2024-01-01"})
        result = store.get("g1")
        assert result is not None
        assert result["token_str"] == "token_string"

    def test_list_all(self):
        store = GrantStore()
        store.add("g1", "t1", {"audience": "A", "policy": "full", "issued_at": "2024-01-01"})
        store.add("g2", "t2", {"audience": "B", "policy": "minimal", "issued_at": "2024-01-01"})
        grants = store.list_all()
        assert len(grants) == 2

    def test_revoke(self):
        store = GrantStore()
        store.add("g1", "t1", {"audience": "A", "issued_at": "2024-01-01"})
        assert store.revoke("g1")
        assert store.get("g1")["revoked"] is True

    def test_revoke_nonexistent(self):
        store = GrantStore()
        assert not store.revoke("nonexistent")


# ============================================================================
# NonceCache unit tests
# ============================================================================

class TestNonceCache:

    def test_fresh_nonce(self):
        cache = NonceCache()
        assert cache.check_and_add("nonce1") is True

    def test_duplicate_nonce(self):
        cache = NonceCache()
        cache.check_and_add("nonce1")
        assert cache.check_and_add("nonce1") is False

    def test_different_nonces(self):
        cache = NonceCache()
        assert cache.check_and_add("a") is True
        assert cache.check_and_add("b") is True

    def test_max_size_eviction(self):
        cache = NonceCache(max_size=5, ttl_seconds=300)
        for i in range(10):
            cache.check_and_add(f"nonce{i}")
        # After adding 10, the cache should have evicted old entries
        # Recent ones should still be there
        assert cache.check_and_add("nonce9") is False  # recent, still in cache
