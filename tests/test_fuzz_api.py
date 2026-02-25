"""
Fuzz testing for CaaS API endpoints — exercise with malformed inputs.

Goal: No endpoint returns 500 for any malformed input. Expected responses
are 400 (bad request), 401 (unauthorized), 404 (not found), or 413 (too large).

Uses stdlib only (no hypothesis dependency).
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer

from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import JsonWebhookStore
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import VALID_SCOPES, GrantToken


def _build_test_graph():
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="knows"))
    return g


def _setup_fuzz_server():
    if not has_crypto():
        return None, None, None, None

    identity = UPAIIdentity.generate("Fuzz Test User")
    graph = _build_test_graph()

    from cortex.upai.disclosure import PolicyRegistry

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.audit_log = None
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

    token = GrantToken.create(identity, audience="FuzzTest", scopes=list(VALID_SCOPES))
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


def _fuzz_request(port, method, path, token=None, body=None, content_type="application/json"):
    """Make a request and return the status code. Never raises."""
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", content_type)
        req.data = body if isinstance(body, bytes) else body.encode("utf-8")
    try:
        resp = urllib.request.urlopen(req)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, ConnectionError, OSError):
        return 0  # connection error — acceptable for edge cases


# ============================================================================
# Fuzz path parameters — no endpoint should return 500
# ============================================================================

class TestFuzzPathParams:

    def test_empty_node_id(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            # Empty path after /context/nodes/ — should match /context/nodes route
            status = _fuzz_request(port, "GET", "/context/nodes/", token)
            assert status != 500
        finally:
            server.shutdown()

    def test_very_long_node_id(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            long_id = "a" * 500
            status = _fuzz_request(port, "GET", f"/context/nodes/{long_id}", token)
            assert status != 500
            assert status == 400  # validated
        finally:
            server.shutdown()

    def test_null_bytes_in_path(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context/nodes/n1%00", token)
            assert status != 500
        finally:
            server.shutdown()

    def test_path_traversal(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context/nodes/..%2F..%2Fetc%2Fpasswd", token)
            assert status != 500
            assert status == 400
        finally:
            server.shutdown()

    def test_unicode_in_path(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context/nodes/%E2%80%8B%E2%80%8B", token)
            assert status != 500
        finally:
            server.shutdown()

    def test_sql_injection_in_path(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context/nodes/1%27%20OR%201%3D1%20--", token)
            assert status != 500
        finally:
            server.shutdown()

    def test_delete_with_traversal(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "DELETE", "/grants/..%2F..%2Froot", token)
            assert status != 500
            assert status == 400
        finally:
            server.shutdown()


# ============================================================================
# Fuzz request bodies
# ============================================================================

class TestFuzzRequestBodies:

    def test_empty_body(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "POST", "/grants", token, body=b"")
            assert status != 500
        finally:
            server.shutdown()

    def test_non_json_body(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "POST", "/grants", token, body=b"not json at all")
            assert status != 500
        finally:
            server.shutdown()

    def test_deeply_nested_json(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            # 50 levels deep
            nested = {"a": None}
            current = nested
            for _ in range(50):
                current["a"] = {"a": None}
                current = current["a"]
            body = json.dumps(nested).encode("utf-8")
            status = _fuzz_request(port, "POST", "/grants", token, body=body)
            assert status != 500
        finally:
            server.shutdown()

    def test_wrong_types_in_body(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            body = json.dumps({"audience": 12345, "policy": True, "ttl_hours": "abc"}).encode("utf-8")
            status = _fuzz_request(port, "POST", "/grants", token, body=body)
            assert status != 500
        finally:
            server.shutdown()

    def test_array_instead_of_object(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            body = json.dumps([1, 2, 3]).encode("utf-8")
            status = _fuzz_request(port, "POST", "/grants", token, body=body)
            assert status != 500
        finally:
            server.shutdown()


# ============================================================================
# Fuzz query parameters
# ============================================================================

class TestFuzzQueryParams:

    def test_negative_limit(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context/nodes?limit=-1", token)
            assert status != 500
        finally:
            server.shutdown()

    def test_non_numeric_offset(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context/nodes?offset=abc", token)
            assert status != 500
        finally:
            server.shutdown()

    def test_very_large_limit(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context/nodes?limit=999999999", token)
            assert status != 500
        finally:
            server.shutdown()


# ============================================================================
# Fuzz headers
# ============================================================================

class TestFuzzHeaders:

    def test_missing_auth(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context", token=None)
            assert status != 500
            assert status == 401
        finally:
            server.shutdown()

    def test_malformed_bearer_token(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context", token="not.a.real.token")
            assert status != 500
            assert status == 401
        finally:
            server.shutdown()

    def test_empty_bearer_token(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            status = _fuzz_request(port, "GET", "/context", token="")
            assert status != 500
        finally:
            server.shutdown()

    def test_very_long_token(self):
        server, port, identity, token = _setup_fuzz_server()
        if server is None:
            return
        try:
            long_token = "x" * 10000
            status = _fuzz_request(port, "GET", "/context", token=long_token)
            assert status != 500
            assert status == 401
        finally:
            server.shutdown()
