"""
Tests for CaaS /policies HTTP endpoints and CLI 'policy' subcommand.
"""

import json
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer

from cortex.graph import CortexGraph, Node, Edge
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import GrantToken, VALID_SCOPES
from cortex.upai.disclosure import PolicyRegistry
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache, ThreadingHTTPServer
from cortex.caas.storage import JsonWebhookStore


# ---------------------------------------------------------------------------
# Server setup helpers
# ---------------------------------------------------------------------------

def _build_test_graph() -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    return g


def _setup_server():
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
    CaaSHandler.policy_registry = PolicyRegistry()
    CaaSHandler._allowed_origins = set()
    CaaSHandler.rate_limiter = None
    CaaSHandler.webhook_worker = None
    CaaSHandler.audit_log = None
    CaaSHandler.session_manager = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = None
    CaaSHandler.sse_manager = None
    CaaSHandler.keychain = None
    CaaSHandler.metrics_registry = None

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


def _request(port, method, path, body=None, token=None, expect_error=False):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
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


# ---------------------------------------------------------------------------
# /policies endpoint tests
# ---------------------------------------------------------------------------

class TestPoliciesEndpoints:
    def setup_method(self):
        result = _setup_server()
        if result[0] is None:
            import pytest
            pytest.skip("pynacl not available")
        self.server, self.port, self.identity, self.token = result

    def teardown_method(self):
        if hasattr(self, 'server') and self.server:
            self.server.shutdown()

    def test_list_policies_returns_builtins(self):
        data, status = _request(self.port, "GET", "/policies", token=self.token)
        assert status == 200
        names = [p["name"] for p in data["policies"]]
        assert "full" in names
        assert "professional" in names
        assert "technical" in names
        assert "minimal" in names

    def test_list_policies_builtin_flag(self):
        data, _ = _request(self.port, "GET", "/policies", token=self.token)
        for p in data["policies"]:
            if p["name"] in ("full", "professional", "technical", "minimal"):
                assert p["builtin"] is True

    def test_get_builtin_policy(self):
        data, status = _request(self.port, "GET", "/policies/professional", token=self.token)
        assert status == 200
        assert data["name"] == "professional"
        assert data["builtin"] is True
        assert data["min_confidence"] == 0.6

    def test_get_nonexistent_policy(self):
        data, status = _request(self.port, "GET", "/policies/nope", token=self.token, expect_error=True)
        assert status == 404

    def test_create_custom_policy(self):
        body = {
            "name": "my-policy",
            "include_tags": ["identity", "technical_expertise"],
            "min_confidence": 0.7,
        }
        data, status = _request(self.port, "POST", "/policies", body=body, token=self.token)
        assert status == 201
        assert data["name"] == "my-policy"
        assert data["min_confidence"] == 0.7
        assert data["include_tags"] == ["identity", "technical_expertise"]

    def test_created_policy_appears_in_list(self):
        body = {"name": "listed-policy", "include_tags": ["a"]}
        _request(self.port, "POST", "/policies", body=body, token=self.token)
        data, _ = _request(self.port, "GET", "/policies", token=self.token)
        names = [p["name"] for p in data["policies"]]
        assert "listed-policy" in names

    def test_created_policy_retrievable(self):
        body = {"name": "get-me", "min_confidence": 0.5}
        _request(self.port, "POST", "/policies", body=body, token=self.token)
        data, status = _request(self.port, "GET", "/policies/get-me", token=self.token)
        assert status == 200
        assert data["name"] == "get-me"
        assert data["min_confidence"] == 0.5
        assert data["builtin"] is False

    def test_create_duplicate_fails(self):
        body = {"name": "dup-test"}
        _request(self.port, "POST", "/policies", body=body, token=self.token)
        data, status = _request(self.port, "POST", "/policies", body=body, token=self.token, expect_error=True)
        assert status == 400

    def test_create_without_name_fails(self):
        body = {"include_tags": ["a"]}
        data, status = _request(self.port, "POST", "/policies", body=body, token=self.token, expect_error=True)
        assert status == 400

    def test_create_builtin_name_fails(self):
        body = {"name": "full"}
        data, status = _request(self.port, "POST", "/policies", body=body, token=self.token, expect_error=True)
        assert status == 400

    def test_update_custom_policy(self):
        body = {"name": "updatable", "min_confidence": 0.3}
        _request(self.port, "POST", "/policies", body=body, token=self.token)

        update = {"min_confidence": 0.9, "include_tags": ["new-tag"]}
        data, status = _request(self.port, "PUT", "/policies/updatable", body=update, token=self.token)
        assert status == 200
        assert data["min_confidence"] == 0.9
        assert data["include_tags"] == ["new-tag"]

    def test_update_builtin_fails(self):
        update = {"min_confidence": 0.1}
        data, status = _request(self.port, "PUT", "/policies/full", body=update, token=self.token, expect_error=True)
        assert status == 403

    def test_update_nonexistent_fails(self):
        update = {"min_confidence": 0.5}
        data, status = _request(self.port, "PUT", "/policies/ghost", body=update, token=self.token, expect_error=True)
        assert status == 404

    def test_delete_custom_policy(self):
        body = {"name": "deletable"}
        _request(self.port, "POST", "/policies", body=body, token=self.token)
        data, status = _request(self.port, "DELETE", "/policies/deletable", token=self.token)
        assert status == 200
        assert data["deleted"] is True

        # Verify it's gone
        data, status = _request(self.port, "GET", "/policies/deletable", token=self.token, expect_error=True)
        assert status == 404

    def test_delete_builtin_fails(self):
        data, status = _request(self.port, "DELETE", "/policies/professional", token=self.token, expect_error=True)
        assert status == 403

    def test_delete_nonexistent_fails(self):
        data, status = _request(self.port, "DELETE", "/policies/no-such", token=self.token, expect_error=True)
        assert status == 404

    def test_custom_policy_in_discovery(self):
        body = {"name": "discovery-visible"}
        _request(self.port, "POST", "/policies", body=body, token=self.token)
        data, status = _request(self.port, "GET", "/.well-known/upai-configuration")
        assert "discovery-visible" in data["supported_policies"]

    def test_create_grant_with_custom_policy(self):
        # Create a custom policy first
        _request(self.port, "POST", "/policies", body={"name": "grant-policy"}, token=self.token)
        # Create a grant using the custom policy
        grant_body = {
            "audience": "test-app",
            "policy": "grant-policy",
        }
        data, status = _request(self.port, "POST", "/grants", body=grant_body, token=self.token)
        assert status == 201
        assert data["policy"] == "grant-policy"


# ---------------------------------------------------------------------------
# CLI 'policy' subcommand tests
# ---------------------------------------------------------------------------

class TestPolicyCLI:
    def test_list_policies(self):
        from cortex.cli import main
        result = main(["policy", "--list"])
        assert result == 0

    def test_show_builtin(self):
        from cortex.cli import main
        result = main(["policy", "--show", "full"])
        assert result == 0

    def test_show_nonexistent(self):
        from cortex.cli import main
        result = main(["policy", "--show", "nope"])
        assert result == 1

    def test_create_prints_definition(self):
        from cortex.cli import main
        result = main(["policy", "--create", "--name", "cli-test",
                       "--include-tags", "identity,tech",
                       "--min-confidence", "0.5"])
        assert result == 0

    def test_create_without_name(self):
        from cortex.cli import main
        result = main(["policy", "--create"])
        assert result == 1

    def test_delete_builtin(self):
        from cortex.cli import main
        result = main(["policy", "--delete", "full"])
        assert result == 1

    def test_no_args(self):
        from cortex.cli import main
        result = main(["policy"])
        assert result == 1
