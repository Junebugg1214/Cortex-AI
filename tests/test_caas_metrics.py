"""
Integration tests for CaaS /metrics endpoint — start server with metrics enabled,
make requests, scrape /metrics, verify Prometheus output.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer

from cortex.caas.instrumentation import (
    create_default_registry,
)
from cortex.caas.server import CaaSHandler, GrantStore, NonceCache
from cortex.caas.storage import JsonWebhookStore
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.disclosure import PolicyRegistry
from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.tokens import GrantToken


def _build_test_graph() -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.95))
    g.add_node(Node(id="n2", label="Python", tags=["technical_expertise"], confidence=0.9))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="knows"))
    return g


def _setup_server_with_metrics():
    if not has_crypto():
        return None, None, None, None

    identity = UPAIIdentity.generate("Metrics Test")
    graph = _build_test_graph()

    # Reset global metric state for test isolation
    registry = create_default_registry()

    CaaSHandler.graph = graph
    CaaSHandler.identity = identity
    CaaSHandler.grant_store = GrantStore()
    CaaSHandler.nonce_cache = NonceCache()
    CaaSHandler.version_store = None
    CaaSHandler.webhook_store = JsonWebhookStore()
    CaaSHandler.policy_registry = PolicyRegistry()
    CaaSHandler.metrics_registry = registry
    CaaSHandler._allowed_origins = set()
    CaaSHandler.rate_limiter = None
    CaaSHandler.webhook_worker = None
    CaaSHandler.audit_log = None
    CaaSHandler.session_manager = None

    server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
    port = server.server_address[1]
    CaaSHandler._allowed_origins = {f"http://127.0.0.1:{port}"}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    token = GrantToken.create(identity, audience="MetricsTest")
    token_str = token.sign(identity)
    CaaSHandler.grant_store.add(token.grant_id, token_str, token.to_dict())

    return server, port, identity, token_str


def _get(port, path, token=None):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    resp = urllib.request.urlopen(req)
    return resp.read().decode(), resp.status


def _get_json(port, path, token=None, expect_error=False):
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


class TestMetricsEndpoint:
    def setup_method(self):
        result = _setup_server_with_metrics()
        if result[0] is None:
            import pytest
            pytest.skip("pynacl not available")
        self.server, self.port, self.identity, self.token = result

    def teardown_method(self):
        if hasattr(self, 'server') and self.server:
            self.server.shutdown()

    def test_metrics_endpoint_exists(self):
        body, status = _get(self.port, "/metrics")
        assert status == 200
        assert "cortex_build_info" in body

    def test_metrics_content_type(self):
        url = f"http://127.0.0.1:{self.port}/metrics"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req)
        ct = resp.headers.get("Content-Type", "")
        assert "text/plain" in ct

    def test_metrics_show_build_info(self):
        body, _ = _get(self.port, "/metrics")
        assert 'version="1.0.0"' in body

    def test_metrics_count_requests(self):
        # Make some requests
        _get(self.port, "/health")
        _get(self.port, "/health")
        _get_json(self.port, "/", self.token)

        body, _ = _get(self.port, "/metrics")
        assert "cortex_http_requests_total" in body
        # Health should have been counted
        assert "/health" in body

    def test_metrics_graph_gauges(self):
        body, _ = _get(self.port, "/metrics")
        # Graph has 2 nodes and 1 edge
        assert "cortex_graph_nodes" in body
        assert "cortex_graph_edges" in body
        lines = body.split("\n")
        node_lines = [l for l in lines if l.startswith("cortex_graph_nodes ")]
        edge_lines = [l for l in lines if l.startswith("cortex_graph_edges ")]
        assert any("2.0" in l for l in node_lines)
        assert any("1.0" in l for l in edge_lines)

    def test_metrics_grants_gauge(self):
        body, _ = _get(self.port, "/metrics")
        assert "cortex_grants_active" in body
        lines = body.split("\n")
        grant_lines = [l for l in lines if l.startswith("cortex_grants_active ")]
        assert any("1.0" in l for l in grant_lines)

    def test_metrics_duration_histogram(self):
        _get(self.port, "/health")
        body, _ = _get(self.port, "/metrics")
        assert "cortex_http_request_duration_seconds" in body
        assert "cortex_http_request_duration_seconds_bucket" in body
        assert "cortex_http_request_duration_seconds_sum" in body
        assert "cortex_http_request_duration_seconds_count" in body

    def test_metrics_no_auth_required(self):
        # /metrics should be accessible without a token
        body, status = _get(self.port, "/metrics")
        assert status == 200

    def test_metrics_path_normalization(self):
        # Request a path with an ID-like segment
        _get_json(self.port, "/context/nodes/n1", self.token)
        body, _ = _get(self.port, "/metrics")
        # The path should be normalized to /context/nodes/:id or similar
        # At minimum, we should see the request counted
        assert "cortex_http_requests_total" in body


class TestMetricsDisabled:
    """Test that server works fine with metrics disabled."""

    def setup_method(self):
        if not has_crypto():
            import pytest
            pytest.skip("pynacl not available")

        identity = UPAIIdentity.generate("No Metrics")
        graph = _build_test_graph()

        CaaSHandler.graph = graph
        CaaSHandler.identity = identity
        CaaSHandler.grant_store = GrantStore()
        CaaSHandler.nonce_cache = NonceCache()
        CaaSHandler.version_store = None
        CaaSHandler.webhook_store = JsonWebhookStore()
        CaaSHandler.policy_registry = PolicyRegistry()
        CaaSHandler.metrics_registry = None  # disabled
        CaaSHandler._allowed_origins = set()
        CaaSHandler.rate_limiter = None
        CaaSHandler.webhook_worker = None
        CaaSHandler.audit_log = None
        CaaSHandler.session_manager = None

        self.server = HTTPServer(("127.0.0.1", 0), CaaSHandler)
        self.port = self.server.server_address[1]
        CaaSHandler._allowed_origins = {f"http://127.0.0.1:{self.port}"}

        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)

    def teardown_method(self):
        if hasattr(self, 'server') and self.server:
            self.server.shutdown()

    def test_metrics_disabled_returns_404(self):
        try:
            url = f"http://127.0.0.1:{self.port}/metrics"
            urllib.request.urlopen(url)
            assert False, "Should have raised HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_health_still_works(self):
        data, status = _get_json(self.port, "/health")
        assert status == 200
        assert data["status"] == "ok"
