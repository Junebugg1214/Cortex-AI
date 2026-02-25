"""
Tests for path parameter validation — null bytes, path traversal, extreme lengths.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from cortex.caas.validation import (
    is_valid_safe_id,
    validate_grant_id,
    validate_node_id,
    validate_path_param,
    validate_policy_name,
    validate_version_id,
    validate_webhook_id,
)
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import InMemoryAuditLog, JsonWebhookStore
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import VALID_SCOPES, GrantToken


# ============================================================================
# Unit tests — validation functions
# ============================================================================

class TestValidatePathParam:

    def test_valid_simple_id(self):
        ok, msg = validate_path_param("abc123")
        assert ok is True

    def test_empty_rejected(self):
        ok, msg = validate_path_param("")
        assert ok is False
        assert "empty" in msg

    def test_null_byte_rejected(self):
        ok, msg = validate_path_param("abc\x00def")
        assert ok is False
        assert "null" in msg

    def test_slash_rejected(self):
        ok, msg = validate_path_param("abc/def")
        assert ok is False
        assert "/" in msg

    def test_path_traversal_rejected(self):
        ok, msg = validate_path_param("abc..def")
        assert ok is False
        assert ".." in msg

    def test_too_long_rejected(self):
        ok, msg = validate_path_param("x" * 257)
        assert ok is False
        assert "256" in msg

    def test_max_length_accepted(self):
        ok, msg = validate_path_param("x" * 256)
        assert ok is True


class TestSafeId:

    def test_valid_ids(self):
        assert is_valid_safe_id("abc123") is True
        assert is_valid_safe_id("node-1") is True
        assert is_valid_safe_id("my_node.v2") is True
        assert is_valid_safe_id("a:b:c") is True

    def test_invalid_ids(self):
        assert is_valid_safe_id("") is False
        assert is_valid_safe_id("abc def") is False  # space
        assert is_valid_safe_id("abc/def") is False  # slash
        assert is_valid_safe_id("x" * 257) is False  # too long


class TestValidateNodeId:

    def test_valid(self):
        ok, msg = validate_node_id("n1")
        assert ok is True

    def test_null_byte(self):
        ok, msg = validate_node_id("n1\x00")
        assert ok is False

    def test_special_chars(self):
        ok, msg = validate_node_id("n1 OR 1=1")
        assert ok is False


class TestValidateGrantId:

    def test_valid_uuid(self):
        ok, msg = validate_grant_id("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
        assert ok is True

    def test_invalid_format(self):
        ok, msg = validate_grant_id("not-a-uuid")
        assert ok is False


class TestValidateWebhookId:

    def test_valid_uuid(self):
        ok, msg = validate_webhook_id("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
        assert ok is True

    def test_invalid(self):
        ok, msg = validate_webhook_id("xxx")
        assert ok is False


class TestValidateVersionId:

    def test_valid_hex32(self):
        ok, msg = validate_version_id("a" * 32)
        assert ok is True

    def test_invalid(self):
        ok, msg = validate_version_id("short")
        assert ok is False


class TestValidatePolicyName:

    def test_valid(self):
        ok, msg = validate_policy_name("my-policy_v2")
        assert ok is True

    def test_too_long(self):
        ok, msg = validate_policy_name("x" * 65)
        assert ok is False

    def test_special_chars(self):
        ok, msg = validate_policy_name("policy; DROP TABLE")
        assert ok is False


# ============================================================================
# Integration tests — server returns 400 for invalid path IDs
# ============================================================================

def _build_test_graph():
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="knows"))
    return g


def _setup_server():
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

    token = GrantToken.create(identity, audience="Test", scopes=list(VALID_SCOPES))
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


def _request(port, method, path, token=None):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if method in ("POST", "PUT", "DELETE"):
        req.add_header("Content-Type", "application/json")
        req.data = b"{}"
    try:
        resp = urllib.request.urlopen(req)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code


class TestPathValidationIntegration:

    def test_null_byte_in_node_id_returns_400(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            status = _request(port, "GET", "/context/nodes/n1%00evil", token)
            assert status == 400
        finally:
            server.shutdown()

    def test_path_traversal_in_node_id_returns_400(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            status = _request(port, "GET", "/context/nodes/..%2F..%2Fetc%2Fpasswd", token)
            assert status == 400
        finally:
            server.shutdown()

    def test_too_long_id_returns_400(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            long_id = "x" * 300
            status = _request(port, "GET", f"/context/nodes/{long_id}", token)
            assert status == 400
        finally:
            server.shutdown()

    def test_valid_node_id_still_works(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            status = _request(port, "GET", "/context/nodes/n1", token)
            assert status == 200
        finally:
            server.shutdown()

    def test_delete_with_null_byte_returns_400(self):
        server, port, identity, token = _setup_server()
        if server is None:
            return
        try:
            status = _request(port, "DELETE", "/grants/abc%00def", token)
            assert status == 400
        finally:
            server.shutdown()
