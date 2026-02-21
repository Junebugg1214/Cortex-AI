"""Tests for the Python SDK client — uses a real HTTPServer on a random port."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

# Ensure the SDK package is importable
SDK_DIR = Path(__file__).resolve().parent.parent / "sdk" / "python"
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from cortex_sdk import CortexClient  # noqa: E402
from cortex_sdk.exceptions import (  # noqa: E402
    AuthenticationError,
    CortexSDKError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Mock HTTP server
# ---------------------------------------------------------------------------

class MockHandler(BaseHTTPRequestHandler):
    """Simulates CaaS API responses for SDK testing."""

    def log_message(self, format, *args):
        pass  # Suppress request logs

    def _respond(self, code, body, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if isinstance(body, str):
            self.wfile.write(body.encode("utf-8"))
        else:
            self.wfile.write(json.dumps(body).encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?")[0]
        query = self.path.split("?")[1] if "?" in self.path else ""

        if path == "/":
            self._respond(200, {"name": "Cortex", "version": "1.2.1", "did": "did:key:z123"})
        elif path == "/.well-known/upai-configuration":
            self._respond(200, {"endpoints": {"context": "/context"}})
        elif path == "/health":
            self._respond(200, {"status": "ok", "timestamp": "2026-01-01T00:00:00Z"})
        elif path == "/identity":
            self._respond(200, {"id": "did:key:z123", "@context": "https://www.w3.org/ns/did/v1"})
        elif path == "/context":
            self._respond(200, {"nodes": [], "edges": []})
        elif path == "/context/compact":
            self._respond(200, "# Context\n\nEmpty graph", content_type="text/markdown")
        elif path == "/context/nodes":
            # Paginated response
            items = [{"id": "n1", "label": "Node1"}, {"id": "n2", "label": "Node2"}]
            if "cursor=page2" in query:
                self._respond(200, {"items": [{"id": "n3", "label": "Node3"}], "has_more": False})
            else:
                self._respond(200, {"items": items, "has_more": True, "next_cursor": "page2"})
        elif path.startswith("/context/nodes/"):
            node_id = path.split("/")[-1]
            if node_id == "missing":
                self._respond(404, {"error": {"code": "UPAI-4003", "type": "not_found", "message": "node not found"}})
            else:
                self._respond(200, {"id": node_id, "label": "Test Node"})
        elif path == "/context/edges":
            self._respond(200, {"items": [{"source": "n1", "target": "n2", "relation": "related_to"}], "has_more": False})
        elif path == "/context/stats":
            self._respond(200, {"node_count": 10, "edge_count": 5, "avg_degree": 1.0})
        elif path == "/versions":
            self._respond(200, {"items": [{"version_id": "v1", "message": "init"}], "has_more": False})
        elif path.startswith("/versions/diff"):
            self._respond(200, {"version_a": "v1", "version_b": "v2", "added_nodes": ["n3"]})
        elif path.startswith("/versions/"):
            vid = path.split("/")[-1]
            self._respond(200, {"version_id": vid, "message": "snapshot"})
        elif path == "/grants":
            self._respond(200, {"grants": [{"grant_id": "g1", "audience": "test"}]})
        elif path == "/webhooks":
            self._respond(200, {"webhooks": [{"webhook_id": "w1", "url": "http://example.com"}]})
        elif path == "/policies":
            self._respond(200, {"policies": [{"name": "full", "builtin": True}]})
        elif path.startswith("/policies/"):
            name = path.split("/")[-1]
            self._respond(200, {"name": name, "builtin": True})
        elif path == "/metrics":
            self._respond(200, "# HELP cortex_build_info\ncortex_build_info 1.0", content_type="text/plain")
        elif path == "/error/401":
            self._respond(401, {"error": {"message": "invalid token"}})
        elif path == "/error/403":
            self._respond(403, {"error": {"message": "insufficient scope"}})
        elif path == "/error/429":
            self._respond(429, {"error": {"message": "rate limited"}})
        elif path == "/error/500":
            self._respond(500, {"error": {"message": "internal error"}})
        elif path == "/error/400":
            self._respond(400, {"error": {"message": "bad request"}})
        else:
            self._respond(404, {"error": {"code": "UPAI-4003", "type": "not_found", "message": "endpoint not found"}})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length).decode()) if content_length else {}
        path = self.path

        if path == "/grants":
            self._respond(200, {
                "grant_id": "g-new",
                "audience": body.get("audience", ""),
                "policy": body.get("policy", "professional"),
                "token": "tok_xxx",
            })
        elif path == "/webhooks":
            self._respond(200, {
                "webhook_id": "w-new",
                "url": body.get("url", ""),
                "events": body.get("events", ["*"]),
            })
        elif path == "/policies":
            self._respond(200, {
                "name": body.get("name", "custom"),
                "builtin": False,
            })
        else:
            self._respond(404, {"error": {"message": "not found"}})

    def do_DELETE(self):
        path = self.path
        if path.startswith("/grants/"):
            self._respond(200, {"status": "revoked"})
        elif path.startswith("/webhooks/"):
            self._respond(200, {"status": "deleted"})
        elif path.startswith("/policies/"):
            self._respond(200, {"status": "deleted"})
        else:
            self._respond(404, {"error": {"message": "not found"}})


@pytest.fixture(scope="module")
def server():
    """Start mock HTTP server on a random port."""
    srv = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture
def client(server):
    return CortexClient(base_url=server, token="test-token", timeout=5.0)


@pytest.fixture
def noauth_client(server):
    return CortexClient(base_url=server, timeout=5.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_info(self, client):
        info = client.info()
        assert info["name"] == "Cortex"
        assert info["version"] == "1.2.1"

    def test_discovery(self, client):
        disc = client.discovery()
        assert "endpoints" in disc

    def test_health(self, client):
        h = client.health()
        assert h["status"] == "ok"

    def test_identity(self, client):
        ident = client.identity()
        assert "id" in ident


class TestContext:
    def test_context(self, client):
        ctx = client.context()
        assert "nodes" in ctx

    def test_context_compact(self, client):
        md = client.context_compact()
        assert isinstance(md, str)
        assert "Context" in md

    def test_nodes_pagination(self, client):
        all_nodes = list(client.nodes(limit=20))
        assert len(all_nodes) == 3
        assert all_nodes[0]["id"] == "n1"
        assert all_nodes[2]["id"] == "n3"

    def test_single_node(self, client):
        node = client.node("abc")
        assert node["id"] == "abc"
        assert node["label"] == "Test Node"

    def test_edges(self, client):
        all_edges = list(client.edges())
        assert len(all_edges) == 1
        assert all_edges[0]["relation"] == "related_to"

    def test_stats(self, client):
        s = client.stats()
        assert s["node_count"] == 10


class TestVersions:
    def test_versions_iterator(self, client):
        vs = list(client.versions())
        assert len(vs) == 1
        assert vs[0]["version_id"] == "v1"

    def test_single_version(self, client):
        v = client.version("v1")
        assert v["version_id"] == "v1"

    def test_version_diff(self, client):
        diff = client.version_diff("v1", "v2")
        assert "added_nodes" in diff


class TestGrants:
    def test_create_grant(self, client):
        g = client.create_grant(audience="test-app", policy="professional")
        assert g["grant_id"] == "g-new"
        assert g["audience"] == "test-app"

    def test_create_grant_with_scopes(self, client):
        g = client.create_grant(audience="app", scopes=["read:context", "read:versions"])
        assert g["grant_id"] == "g-new"

    def test_list_grants(self, client):
        grants = client.list_grants()
        assert len(grants) == 1
        assert grants[0]["grant_id"] == "g1"

    def test_revoke_grant(self, client):
        result = client.revoke_grant("g1")
        assert result["status"] == "revoked"


class TestWebhooks:
    def test_create_webhook(self, client):
        wh = client.create_webhook(url="http://example.com/hook")
        assert wh["webhook_id"] == "w-new"

    def test_create_webhook_with_events(self, client):
        wh = client.create_webhook(url="http://example.com/hook", events=["node.created"])
        assert wh["webhook_id"] == "w-new"

    def test_list_webhooks(self, client):
        whs = client.list_webhooks()
        assert len(whs) == 1

    def test_delete_webhook(self, client):
        result = client.delete_webhook("w1")
        assert result["status"] == "deleted"


class TestPolicies:
    def test_list_policies(self, client):
        ps = client.list_policies()
        assert len(ps) == 1
        assert ps[0]["name"] == "full"

    def test_create_policy(self, client):
        p = client.create_policy("custom", min_confidence=0.5)
        assert p["name"] == "custom"

    def test_get_policy(self, client):
        p = client.get_policy("full")
        assert p["name"] == "full"

    def test_delete_policy(self, client):
        result = client.delete_policy("custom")
        assert result["status"] == "deleted"


class TestMetrics:
    def test_metrics_returns_string(self, client):
        m = client.metrics()
        assert isinstance(m, str)
        assert "cortex_build_info" in m


class TestErrorMapping:
    def test_401_raises_authentication_error(self, client):
        with pytest.raises(AuthenticationError) as exc_info:
            client._request("GET", "/error/401", auth=False)
        assert exc_info.value.status_code == 401

    def test_403_raises_forbidden_error(self, client):
        with pytest.raises(ForbiddenError) as exc_info:
            client._request("GET", "/error/403", auth=False)
        assert exc_info.value.status_code == 403

    def test_404_raises_not_found_error(self, client):
        with pytest.raises(NotFoundError):
            client.node("missing")

    def test_400_raises_validation_error(self, client):
        with pytest.raises(ValidationError) as exc_info:
            client._request("GET", "/error/400", auth=False)
        assert exc_info.value.status_code == 400

    def test_429_raises_rate_limit_error(self, client):
        with pytest.raises(RateLimitError):
            client._request("GET", "/error/429", auth=False)

    def test_500_raises_server_error(self, client):
        with pytest.raises(ServerError) as exc_info:
            client._request("GET", "/error/500", auth=False)
        assert exc_info.value.status_code == 500


class TestConnectionError:
    def test_unreachable_server(self):
        client = CortexClient(base_url="http://127.0.0.1:1", timeout=0.5)
        with pytest.raises(CortexSDKError, match="Connection error"):
            client.info()


class TestClientDefaults:
    def test_default_base_url(self):
        c = CortexClient()
        assert c.base_url == "http://localhost:8421"

    def test_trailing_slash_stripped(self):
        c = CortexClient(base_url="http://localhost:8421/")
        assert c.base_url == "http://localhost:8421"

    def test_default_timeout(self):
        c = CortexClient()
        assert c.timeout == 10.0

    def test_custom_timeout(self):
        c = CortexClient(timeout=30.0)
        assert c.timeout == 30.0


class TestPaginatedIterator:
    def test_single_page(self, client):
        edges = list(client.edges())
        assert len(edges) == 1

    def test_multi_page(self, client):
        nodes = list(client.nodes())
        assert len(nodes) == 3


class TestImports:
    def test_package_version(self):
        import cortex_sdk
        assert cortex_sdk.__version__ == "1.4.0"

    def test_all_exceptions_importable(self):
        from cortex_sdk import (
            CortexClient,
        )
        assert CortexClient is not None

    def test_exception_hierarchy(self):
        assert issubclass(AuthenticationError, CortexSDKError)
        assert issubclass(ForbiddenError, CortexSDKError)
        assert issubclass(NotFoundError, CortexSDKError)
        assert issubclass(ValidationError, CortexSDKError)
        assert issubclass(RateLimitError, CortexSDKError)
        assert issubclass(ServerError, CortexSDKError)
