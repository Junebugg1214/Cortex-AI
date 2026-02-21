"""
Tests for cortex.sdk — CortexClient against a live in-process CaaS server.

Same server setup pattern as test_caas_server.py.
"""

import threading
import time
from http.server import HTTPServer

import pytest

from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import JsonWebhookStore
from cortex.graph import CortexGraph, Edge, Node
from cortex.sdk import CortexClient
from cortex.sdk.exceptions import (
    AuthenticationError,
    CortexSDKError,
    ForbiddenError,
    NotFoundError,
)
from cortex.upai.disclosure import PolicyRegistry
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import GrantToken


def _build_test_graph() -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95,
                     brief="Founder and CEO"))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9,
                     brief="Primary language"))
    g.add_node(Node(id="n3", label="Healthcare", tags=["domain_knowledge"], confidence=0.8,
                     brief="Healthcare domain"))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="knows"))
    g.add_edge(Edge(id="e2", source_id="n2", target_id="n3", relation="used_in"))
    return g


def _setup():
    if not has_crypto():
        return None, None, None, None

    identity = UPAIIdentity.generate("SDK Test")
    graph = _build_test_graph()

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.policy_registry = PolicyRegistry()
    CaaSHandler.metrics_registry = None
    CaaSHandler._allowed_origins = set()
    CaaSHandler.rate_limiter = None
    CaaSHandler.webhook_worker = None
    CaaSHandler.audit_log = None
    CaaSHandler.session_manager = None
    CaaSHandler.oauth_manager = None
    CaaSHandler.credential_store = None
    CaaSHandler.sse_manager = None
    CaaSHandler.keychain = None

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    from cortex.upai.tokens import VALID_SCOPES
    token = GrantToken.create(identity, audience="SDKTest", scopes=list(VALID_SCOPES))
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


class TestSDKClient:
    def setup_method(self):
        result = _setup()
        if result[0] is None:
            pytest.skip("pynacl not available")
        self.server, self.port, self.identity, self.token = result
        self.client = CortexClient(
            base_url=f"http://127.0.0.1:{self.port}",
            token=self.token,
        )

    def teardown_method(self):
        if hasattr(self, 'server') and self.server:
            self.server.shutdown()

    # -- Discovery --

    def test_info(self):
        data = self.client.info()
        assert data["service"] == "UPAI Context-as-a-Service"
        assert data["version"] == "1.0.0"

    def test_discovery(self):
        data = self.client.discovery()
        assert "upai_version" in data
        assert "endpoints" in data
        assert "supported_policies" in data

    def test_health(self):
        data = self.client.health()
        assert data["status"] == "ok"
        assert data["has_identity"] is True
        assert data["has_graph"] is True

    def test_identity(self):
        data = self.client.identity()
        assert data["id"] == self.identity.did

    # -- Context --

    def test_context(self):
        data = self.client.context()
        assert "schema_version" in data or "nodes" in data

    def test_context_compact(self):
        text = self.client.context_compact()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_nodes_pagination(self):
        nodes = list(self.client.nodes(limit=2))
        assert len(nodes) >= 1
        # Each node should have an id
        for node in nodes:
            assert "id" in node

    def test_node_by_id(self):
        data = self.client.node("n1")
        assert data["id"] == "n1"
        assert data["label"] == "Marc"

    def test_node_not_found(self):
        with pytest.raises(NotFoundError):
            self.client.node("nonexistent")

    def test_edges_pagination(self):
        edges = list(self.client.edges(limit=10))
        assert len(edges) >= 1
        for edge in edges:
            assert "id" in edge or "source_id" in edge

    def test_stats(self):
        data = self.client.stats()
        assert "node_count" in data
        assert data["node_count"] == 3
        assert data["edge_count"] == 2

    # -- Grants --

    def test_create_and_list_grants(self):
        result = self.client.create_grant("test-audience", policy="professional")
        assert "grant_id" in result
        assert "token" in result

        grants = self.client.list_grants()
        ids = [g["grant_id"] for g in grants]
        assert result["grant_id"] in ids

    def test_revoke_grant(self):
        result = self.client.create_grant("revoke-me")
        gid = result["grant_id"]

        revoke = self.client.revoke_grant(gid)
        assert revoke["revoked"] is True

    def test_revoke_nonexistent_grant(self):
        with pytest.raises(NotFoundError):
            self.client.revoke_grant("no-such-grant")

    # -- Webhooks --

    def test_create_and_list_webhooks(self):
        result = self.client.create_webhook(
            url="https://example.com/hook",
            events=["grant.created"],
        )
        assert "webhook_id" in result
        assert "secret" in result

        webhooks = self.client.list_webhooks()
        ids = [w["webhook_id"] for w in webhooks]
        assert result["webhook_id"] in ids

    def test_delete_webhook(self):
        result = self.client.create_webhook(url="https://example.com/del")
        wid = result["webhook_id"]

        delete = self.client.delete_webhook(wid)
        assert delete["deleted"] is True

    def test_delete_nonexistent_webhook(self):
        with pytest.raises(NotFoundError):
            self.client.delete_webhook("no-such-webhook")

    # -- Policies --

    def test_list_policies(self):
        policies = self.client.list_policies()
        names = [p["name"] for p in policies]
        assert "full" in names
        assert "professional" in names

    def test_create_policy(self):
        result = self.client.create_policy(
            "sdk-test-policy",
            include_tags=["identity"],
            min_confidence=0.5,
        )
        assert result["name"] == "sdk-test-policy"
        assert result["min_confidence"] == 0.5

    def test_get_policy(self):
        self.client.create_policy("get-me-policy")
        result = self.client.get_policy("get-me-policy")
        assert result["name"] == "get-me-policy"

    def test_delete_policy(self):
        self.client.create_policy("del-me-policy")
        result = self.client.delete_policy("del-me-policy")
        assert result["deleted"] is True

    def test_delete_builtin_policy_forbidden(self):
        with pytest.raises(ForbiddenError):
            self.client.delete_policy("full")

    # -- Auth errors --

    def test_no_token_raises_auth_error(self):
        unauth = CortexClient(
            base_url=f"http://127.0.0.1:{self.port}",
            token="",
        )
        with pytest.raises(AuthenticationError):
            unauth.context()

    def test_bad_token_raises_auth_error(self):
        bad = CortexClient(
            base_url=f"http://127.0.0.1:{self.port}",
            token="invalid-token-value",
        )
        with pytest.raises(AuthenticationError):
            bad.context()

    # -- Connection error --

    def test_connection_error(self):
        client = CortexClient(base_url="http://127.0.0.1:1", timeout=1.0)
        with pytest.raises(CortexSDKError, match="Connection error"):
            client.health()


class TestSDKImports:
    """Test that the SDK package exports are correct."""

    def test_import_client(self):
        from cortex.sdk import CortexClient
        assert CortexClient is not None

    def test_import_exceptions(self):
        from cortex.sdk import (
            AuthenticationError,
            CortexSDKError,
            ForbiddenError,
            NotFoundError,
            RateLimitError,
            ServerError,
            ValidationError,
        )
        # All should be subclasses of CortexSDKError
        for exc_class in [AuthenticationError, ForbiddenError, NotFoundError,
                          ValidationError, RateLimitError, ServerError]:
            assert issubclass(exc_class, CortexSDKError)
