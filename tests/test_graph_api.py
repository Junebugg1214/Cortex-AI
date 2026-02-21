"""Tests for Graph Intelligence API — search, path-finding, CRUD, batch, auth."""

from __future__ import annotations

import json
import threading

import pytest

from cortex.graph import CortexGraph, Edge, Node

# ---------------------------------------------------------------------------
# Graph search / traversal unit tests (no HTTP)
# ---------------------------------------------------------------------------

def _build_test_graph() -> CortexGraph:
    """Build a small test graph for unit tests.

    A --knows--> B --works_with--> C
    A --likes--> D
    """
    g = CortexGraph()
    g.add_node(Node(id="a", label="Alice", tags=["person"], confidence=0.9,
                     brief="Alice is an engineer", full_description="Alice works at Acme Corp",
                     properties={"role": "engineer", "city": "Seattle"}))
    g.add_node(Node(id="b", label="Bob", tags=["person"], confidence=0.8,
                     brief="Bob is a designer"))
    g.add_node(Node(id="c", label="Carol", tags=["person"], confidence=0.7,
                     brief="Carol is a manager"))
    g.add_node(Node(id="d", label="Docker", tags=["technology"], confidence=0.6,
                     brief="Container platform"))
    g.add_node(Node(id="e", label="Isolated", tags=["misc"], confidence=0.3,
                     brief="No connections"))
    g.add_edge(Edge(id="ab", source_id="a", target_id="b", relation="knows"))
    g.add_edge(Edge(id="bc", source_id="b", target_id="c", relation="works_with"))
    g.add_edge(Edge(id="ad", source_id="a", target_id="d", relation="uses"))
    return g


# ---------------------------------------------------------------------------
# TestGraphSearch
# ---------------------------------------------------------------------------

class TestGraphSearch:
    def test_search_by_label(self):
        g = _build_test_graph()
        results = g.search_nodes("Alice")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_search_case_insensitive(self):
        g = _build_test_graph()
        results = g.search_nodes("alice")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_search_by_brief(self):
        g = _build_test_graph()
        results = g.search_nodes("engineer")
        assert any(r.id == "a" for r in results)

    def test_search_by_full_description(self):
        g = _build_test_graph()
        results = g.search_nodes("Acme Corp")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_search_by_property_value(self):
        g = _build_test_graph()
        results = g.search_nodes("Seattle")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_search_confidence_filter(self):
        g = _build_test_graph()
        results = g.search_nodes("Container", min_confidence=0.7)
        assert len(results) == 0  # Docker has 0.6 confidence

    def test_search_limit(self):
        g = _build_test_graph()
        # Add more nodes that match
        for i in range(10):
            g.add_node(Node(id=f"test{i}", label=f"Person {i}", brief="A test person"))
        results = g.search_nodes("person", limit=3)
        assert len(results) == 3

    def test_search_field_filter(self):
        g = _build_test_graph()
        # Search only in label — should not find "engineer" in brief
        results = g.search_nodes("engineer", fields=["label"])
        assert len(results) == 0

    def test_search_empty_query(self):
        g = _build_test_graph()
        results = g.search_nodes("")
        assert len(results) == 0

    def test_search_no_match(self):
        g = _build_test_graph()
        results = g.search_nodes("zzzznonexistent")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# TestShortestPath
# ---------------------------------------------------------------------------

class TestShortestPath:
    def test_direct_neighbor(self):
        g = _build_test_graph()
        path = g.shortest_path("a", "b")
        assert path == ["a", "b"]

    def test_two_hop(self):
        g = _build_test_graph()
        path = g.shortest_path("a", "c")
        assert path == ["a", "b", "c"]

    def test_unreachable(self):
        g = _build_test_graph()
        path = g.shortest_path("a", "e")  # e is isolated
        assert path == []

    def test_same_node(self):
        g = _build_test_graph()
        path = g.shortest_path("a", "a")
        assert path == ["a"]

    def test_nonexistent_source(self):
        g = _build_test_graph()
        path = g.shortest_path("nonexistent", "b")
        assert path == []

    def test_nonexistent_target(self):
        g = _build_test_graph()
        path = g.shortest_path("a", "nonexistent")
        assert path == []

    def test_max_depth_respected(self):
        g = _build_test_graph()
        # a -> b -> c is 2 hops, max_depth=1 should not find it
        path = g.shortest_path("a", "c", max_depth=1)
        assert path == []

    def test_reverse_direction(self):
        g = _build_test_graph()
        # BFS treats edges as bidirectional
        path = g.shortest_path("b", "a")
        assert path == ["b", "a"]


# ---------------------------------------------------------------------------
# TestKHop
# ---------------------------------------------------------------------------

class TestKHop:
    def test_one_hop(self):
        g = _build_test_graph()
        nodes, edges = g.k_hop_neighborhood("a", k=1)
        assert "a" in nodes
        assert "b" in nodes  # direct neighbor
        assert "d" in nodes  # direct neighbor
        assert "c" not in nodes  # 2 hops away

    def test_two_hop(self):
        g = _build_test_graph()
        nodes, edges = g.k_hop_neighborhood("a", k=2)
        assert "a" in nodes
        assert "b" in nodes
        assert "c" in nodes  # now reachable
        assert "d" in nodes

    def test_isolated_node(self):
        g = _build_test_graph()
        nodes, edges = g.k_hop_neighborhood("e", k=2)
        assert nodes == {"e"}
        assert edges == set()

    def test_nonexistent_node(self):
        g = _build_test_graph()
        nodes, edges = g.k_hop_neighborhood("nonexistent", k=1)
        assert nodes == set()
        assert edges == set()

    def test_edges_included(self):
        g = _build_test_graph()
        nodes, edges = g.k_hop_neighborhood("a", k=1)
        assert "ab" in edges
        assert "ad" in edges


# ---------------------------------------------------------------------------
# TestUpdateNode
# ---------------------------------------------------------------------------

class TestUpdateNode:
    def test_partial_update(self):
        g = _build_test_graph()
        node = g.update_node("a", {"brief": "Updated brief", "confidence": 0.95})
        assert node is not None
        assert node.brief == "Updated brief"
        assert node.confidence == 0.95
        assert node.label == "Alice"  # Unchanged

    def test_update_nonexistent(self):
        g = _build_test_graph()
        assert g.update_node("nonexistent", {"brief": "x"}) is None

    def test_update_sets_last_seen(self):
        g = _build_test_graph()
        node = g.update_node("a", {"brief": "x"})
        assert node.last_seen != ""

    def test_update_ignores_unknown_fields(self):
        g = _build_test_graph()
        node = g.update_node("a", {"unknown_field": "value", "brief": "new"})
        assert node.brief == "new"
        assert not hasattr(node, "unknown_field")


# ---------------------------------------------------------------------------
# HTTP Integration Tests using live server
# ---------------------------------------------------------------------------

def _start_test_server(graph=None, identity=None, port=0):
    """Start a CaaS test server on a random port."""
    from cortex.caas.server import start_caas_server
    from cortex.upai.identity import UPAIIdentity

    if identity is None:
        identity = UPAIIdentity.generate("test-identity")
    if graph is None:
        graph = _build_test_graph()

    server = start_caas_server(graph=graph, identity=identity, port=port)
    # Get assigned port
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, identity, actual_port


def _create_grant(identity, scopes=None, role=""):
    """Create a grant token string for testing."""
    from cortex.upai.tokens import GrantToken
    token = GrantToken.create(identity, audience="test", scopes=scopes)
    if role:
        token.role = role
    return token.sign(identity)


class TestNodeMutationsHTTP:
    """Test node CRUD via HTTP endpoints."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server, self.identity, self.port = _start_test_server()
        yield
        self.server.shutdown()

    def _request(self, method, path, body=None, token=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body_bytes = json.dumps(body).encode() if body else None
        conn.request(method, path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data) if data else {}

    def test_create_node(self):
        token = _create_grant(self.identity, scopes=["context:write", "context:read"])
        status, data = self._request("POST", "/context/nodes", {
            "label": "NewNode",
            "tags": ["test"],
            "confidence": 0.85,
            "brief": "A test node",
        }, token)
        assert status == 201
        assert data["label"] == "NewNode"
        assert data["confidence"] == 0.85

    def test_update_node(self):
        token = _create_grant(self.identity, scopes=["context:write", "context:read"])
        status, data = self._request("PUT", "/context/nodes/a", {
            "brief": "Updated via API",
        }, token)
        assert status == 200
        assert data["brief"] == "Updated via API"
        assert data["label"] == "Alice"

    def test_delete_node(self):
        token = _create_grant(self.identity, scopes=["context:write", "context:read"])
        # Delete node d
        status, data = self._request("DELETE", "/context/nodes/d", token=token)
        assert status == 200
        assert data["deleted"] is True
        # Verify node is gone
        status2, data2 = self._request("GET", "/context/nodes/d", token=token)
        assert status2 == 404

    def test_delete_node_cascades_edges(self):
        token = _create_grant(self.identity, scopes=["context:write", "context:read"])
        # Node a has edges ab and ad
        status, _ = self._request("DELETE", "/context/nodes/a", token=token)
        assert status == 200

    def test_create_node_missing_label(self):
        token = _create_grant(self.identity, scopes=["context:write"])
        status, data = self._request("POST", "/context/nodes", {"tags": ["x"]}, token)
        assert status == 400


class TestEdgeMutationsHTTP:
    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server, self.identity, self.port = _start_test_server()
        yield
        self.server.shutdown()

    def _request(self, method, path, body=None, token=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body_bytes = json.dumps(body).encode() if body else None
        conn.request(method, path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data) if data else {}

    def test_create_edge(self):
        token = _create_grant(self.identity, scopes=["context:write", "context:read"])
        status, data = self._request("POST", "/context/edges", {
            "source_id": "a",
            "target_id": "c",
            "relation": "mentors",
        }, token)
        assert status == 201
        assert data["relation"] == "mentors"

    def test_create_edge_invalid_source(self):
        token = _create_grant(self.identity, scopes=["context:write"])
        status, data = self._request("POST", "/context/edges", {
            "source_id": "nonexistent",
            "target_id": "b",
            "relation": "x",
        }, token)
        assert status == 404

    def test_delete_edge(self):
        token = _create_grant(self.identity, scopes=["context:write", "context:read"])
        status, data = self._request("DELETE", "/context/edges/ab", token=token)
        assert status == 200
        assert data["deleted"] is True


class TestSearchHTTP:
    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server, self.identity, self.port = _start_test_server()
        yield
        self.server.shutdown()

    def _request(self, method, path, body=None, token=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body_bytes = json.dumps(body).encode() if body else None
        conn.request(method, path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data) if data else {}

    def test_search_nodes(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, data = self._request("POST", "/context/search", {"query": "Alice"}, token)
        assert status == 200
        assert data["count"] == 1
        assert data["results"][0]["label"] == "Alice"

    def test_search_with_confidence_filter(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, data = self._request("POST", "/context/search", {
            "query": "person",
            "min_confidence": 0.8,
        }, token)
        assert status == 200
        # Only Alice (0.9) and Bob (0.8) should match
        for r in data["results"]:
            assert r["confidence"] >= 0.8


class TestPathHTTP:
    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server, self.identity, self.port = _start_test_server()
        yield
        self.server.shutdown()

    def _request(self, method, path, body=None, token=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request(method, path, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data) if data else {}

    def test_shortest_path(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, data = self._request("GET", "/context/path/a/c", token=token)
        assert status == 200
        assert data["path"] == ["a", "b", "c"]
        assert data["length"] == 2

    def test_unreachable_path(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, data = self._request("GET", "/context/path/a/e", token=token)
        assert status == 200
        assert data["path"] == []
        assert data["length"] == -1


class TestNeighborsHTTP:
    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server, self.identity, self.port = _start_test_server()
        yield
        self.server.shutdown()

    def _request(self, method, path, token=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request(method, path, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data) if data else {}

    def test_get_neighbors(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, data = self._request("GET", "/context/nodes/a/neighbors", token)
        assert status == 200
        assert data["count"] == 2  # b and d

    def test_get_neighbors_with_relation_filter(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, data = self._request("GET", "/context/nodes/a/neighbors?relation=knows", token)
        assert status == 200
        assert data["count"] == 1
        assert data["neighbors"][0]["node"]["label"] == "Bob"


class TestBatchOperationsHTTP:
    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server, self.identity, self.port = _start_test_server()
        yield
        self.server.shutdown()

    def _request(self, method, path, body=None, token=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body_bytes = json.dumps(body).encode() if body else None
        conn.request(method, path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data) if data else {}

    def test_batch_create(self):
        token = _create_grant(self.identity, scopes=["context:write"])
        status, data = self._request("POST", "/context/batch", {
            "operations": [
                {"op": "create_node", "label": "Node1", "tags": ["test"]},
                {"op": "create_node", "label": "Node2", "tags": ["test"]},
            ],
        }, token)
        assert status == 200
        assert data["count"] == 2
        assert all(r["status"] == "ok" for r in data["results"])

    def test_batch_mixed_operations(self):
        token = _create_grant(self.identity, scopes=["context:write"])
        status, data = self._request("POST", "/context/batch", {
            "operations": [
                {"op": "create_node", "label": "BatchNode", "id": "batch1"},
                {"op": "update_node", "id": "a", "brief": "Batch-updated"},
                {"op": "delete_node", "id": "e"},  # isolated node
            ],
        }, token)
        assert status == 200
        assert data["count"] == 3

    def test_batch_unknown_op(self):
        token = _create_grant(self.identity, scopes=["context:write"])
        status, data = self._request("POST", "/context/batch", {
            "operations": [
                {"op": "nonexistent_op"},
            ],
        }, token)
        assert status == 200
        assert data["results"][0]["status"] == "unknown_operation"


class TestMutationAuth:
    """Test that context:write scope is required for mutations."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server, self.identity, self.port = _start_test_server()
        yield
        self.server.shutdown()

    def _request(self, method, path, body=None, token=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body_bytes = json.dumps(body).encode() if body else None
        conn.request(method, path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data) if data else {}

    def test_reader_cannot_create_node(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, data = self._request("POST", "/context/nodes", {
            "label": "Forbidden",
        }, token)
        assert status == 403

    def test_reader_cannot_delete_node(self):
        token = _create_grant(self.identity, scopes=["context:read"])
        status, _ = self._request("DELETE", "/context/nodes/a", token=token)
        assert status == 403

    def test_writer_can_create_node(self):
        token = _create_grant(self.identity, scopes=["context:write", "context:read"])
        status, _ = self._request("POST", "/context/nodes", {
            "label": "Allowed",
        }, token)
        assert status == 201

    def test_editor_role_can_write(self):
        from cortex.upai.rbac import scopes_for_role
        scopes = list(scopes_for_role("editor"))
        token = _create_grant(self.identity, scopes=scopes)
        status, _ = self._request("POST", "/context/nodes", {
            "label": "Editor Node",
        }, token)
        assert status == 201
