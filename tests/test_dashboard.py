"""
Tests for Cortex Phase 6: Dashboard (v6.0)

Covers:
- Dashboard HTML generation
- API endpoint responses (/api/stats, /api/gaps, /api/components, /api/graph)
- Server lifecycle
"""

import json
import sys
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

from cortex.graph import CortexGraph, Node, Edge
from cortex.dashboard.server import DashboardHandler, _build_dashboard_html


# ============================================================================
# Dashboard HTML generation
# ============================================================================

class TestDashboardHTML:

    def test_contains_doctype(self):
        html = _build_dashboard_html()
        assert "<!DOCTYPE html>" in html

    def test_contains_poll_logic(self):
        html = _build_dashboard_html()
        assert "setInterval" in html
        assert "5000" in html

    def test_contains_stats_section(self):
        html = _build_dashboard_html()
        assert "stats-card" in html

    def test_contains_gaps_section(self):
        html = _build_dashboard_html()
        assert "gaps-card" in html

    def test_contains_components_section(self):
        html = _build_dashboard_html()
        assert "components-card" in html

    def test_self_contained(self):
        html = _build_dashboard_html()
        assert "http://" not in html
        assert "https://" not in html

    def test_contains_canvas(self):
        html = _build_dashboard_html()
        assert "<canvas" in html


# ============================================================================
# Dashboard API (integration tests with real HTTP server)
# ============================================================================

class TestDashboardAPI:

    @pytest.fixture(autouse=True)
    def setup_server(self):
        """Start a dashboard server on a random port, tear down after."""
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"], confidence=0.9))
        g.add_node(Node(id="n2", label="Health", tags=["domain"], confidence=0.8))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="applied_in"))
        DashboardHandler.graph = g
        self.server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        yield
        self.server.shutdown()

    def _get(self, path: str) -> tuple[int, str]:
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode()

    def test_root_returns_html(self):
        status, body = self._get("/")
        assert status == 200
        assert "<!DOCTYPE html>" in body

    def test_api_stats(self):
        status, body = self._get("/api/stats")
        assert status == 200
        data = json.loads(body)
        assert data["node_count"] == 2
        assert data["edge_count"] == 1

    def test_api_gaps(self):
        status, body = self._get("/api/gaps")
        assert status == 200
        data = json.loads(body)
        assert "category_gaps" in data
        assert "confidence_gaps" in data
        assert "isolated_nodes" in data

    def test_api_components(self):
        status, body = self._get("/api/components")
        assert status == 200
        data = json.loads(body)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["size"] == 2

    def test_api_graph(self):
        status, body = self._get("/api/graph")
        assert status == 200
        data = json.loads(body)
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

    def test_api_graph_has_positions(self):
        _, body = self._get("/api/graph")
        data = json.loads(body)
        node = data["nodes"][0]
        assert "x" in node
        assert "y" in node
        assert "r" in node
        assert "color" in node

    def test_404_for_unknown_path(self):
        try:
            self._get("/nonexistent")
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 404


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
