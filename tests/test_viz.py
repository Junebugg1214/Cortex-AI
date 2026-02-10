"""
Tests for Cortex Phase 6: Visualization (v6.0)

Covers:
- Layout: fruchterman_reingold, cache key, pure Python path,
  deterministic seed, progress callback, max_nodes limit, caching
- Renderer: render_html, render_svg, tag colors, node sizing
"""

import sys

import pytest

from cortex.graph import CortexGraph, Node, Edge, CATEGORY_ORDER
from cortex.viz.layout import (
    fruchterman_reingold, _layout_cache_key, _fr_pure, _build_adjacency,
)
from cortex.viz.renderer import (
    render_html, render_svg, _tag_color, _node_radius, TAG_COLORS,
    _html_escape,
)


# ============================================================================
# Layout cache key
# ============================================================================

class TestLayoutCacheKey:

    def test_same_graph_same_key(self):
        ids = ["a", "b"]
        edges = [("a", "b")]
        assert _layout_cache_key(ids, edges) == _layout_cache_key(ids, edges)

    def test_different_nodes_different_key(self):
        k1 = _layout_cache_key(["a", "b"], [("a", "b")])
        k2 = _layout_cache_key(["a", "c"], [("a", "c")])
        assert k1 != k2

    def test_different_edges_different_key(self):
        ids = ["a", "b", "c"]
        k1 = _layout_cache_key(ids, [("a", "b")])
        k2 = _layout_cache_key(ids, [("a", "c")])
        assert k1 != k2

    def test_order_independent_for_nodes(self):
        """Node order doesn't matter (sorted internally)."""
        k1 = _layout_cache_key(["b", "a"], [("a", "b")])
        k2 = _layout_cache_key(["a", "b"], [("a", "b")])
        assert k1 == k2


# ============================================================================
# Build adjacency
# ============================================================================

class TestBuildAdjacency:

    def test_basic(self):
        adj = _build_adjacency(["a", "b", "c"], [("a", "b")])
        assert "b" in adj["a"]
        assert "a" in adj["b"]
        assert len(adj["c"]) == 0

    def test_empty(self):
        adj = _build_adjacency([], [])
        assert adj == {}


# ============================================================================
# Fruchterman-Reingold layout
# ============================================================================

class TestFruchtermanReingold:

    def _simple_graph(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"], confidence=0.9))
        g.add_node(Node(id="b", label="B", tags=["t"], confidence=0.5))
        g.add_node(Node(id="c", label="C", tags=["t"], confidence=0.3))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        return g

    def test_empty_graph(self):
        assert fruchterman_reingold(CortexGraph()) == {}

    def test_single_node(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        layout = fruchterman_reingold(g, width=1.0, height=1.0)
        assert len(layout) == 1
        x, y = layout["a"]
        assert x == pytest.approx(0.5, abs=0.01)
        assert y == pytest.approx(0.5, abs=0.01)

    def test_all_positions_in_bounds(self):
        g = self._simple_graph()
        layout = fruchterman_reingold(g, width=1.0, height=1.0)
        for nid, (x, y) in layout.items():
            assert 0.0 <= x <= 1.0, f"Node {nid} x={x} out of bounds"
            assert 0.0 <= y <= 1.0, f"Node {nid} y={y} out of bounds"

    def test_deterministic_with_seed(self):
        g = self._simple_graph()
        l1 = fruchterman_reingold(g, seed=42)
        # Clear cache for second run
        if hasattr(g, "_layout_cache"):
            del g._layout_cache
        l2 = fruchterman_reingold(g, seed=42)
        for nid in l1:
            assert l1[nid][0] == pytest.approx(l2[nid][0], abs=0.001)
            assert l1[nid][1] == pytest.approx(l2[nid][1], abs=0.001)

    def test_different_seeds_different_layout(self):
        g = self._simple_graph()
        l1 = fruchterman_reingold(g, seed=42)
        if hasattr(g, "_layout_cache"):
            del g._layout_cache
        l2 = fruchterman_reingold(g, seed=99)
        # At least one node should differ
        any_diff = any(
            abs(l1[nid][0] - l2[nid][0]) > 0.01 or
            abs(l1[nid][1] - l2[nid][1]) > 0.01
            for nid in l1
        )
        assert any_diff

    def test_progress_callback_called(self):
        g = self._simple_graph()
        calls = []
        def progress(current, total):
            calls.append((current, total))
        if hasattr(g, "_layout_cache"):
            del g._layout_cache
        fruchterman_reingold(g, iterations=10, progress=progress)
        assert len(calls) == 10
        assert calls[0] == (1, 10)
        assert calls[-1] == (10, 10)

    def test_max_nodes_limit(self):
        g = CortexGraph()
        for i in range(30):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"], confidence=0.5))
        layout = fruchterman_reingold(g, max_nodes=10)
        assert len(layout) <= 10

    def test_caching(self):
        g = self._simple_graph()
        if hasattr(g, "_layout_cache"):
            del g._layout_cache
        l1 = fruchterman_reingold(g, seed=42)
        l2 = fruchterman_reingold(g, seed=42)
        # Should be the exact same object (cached)
        assert l1 is l2

    def test_connected_nodes_closer(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_node(Node(id="c", label="C", tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        layout = fruchterman_reingold(g, iterations=50, seed=42)
        # Distance A-B should be less than A-C (A and B are connected)
        import math
        dist_ab = math.sqrt(
            (layout["a"][0] - layout["b"][0])**2 +
            (layout["a"][1] - layout["b"][1])**2
        )
        dist_ac = math.sqrt(
            (layout["a"][0] - layout["c"][0])**2 +
            (layout["a"][1] - layout["c"][1])**2
        )
        assert dist_ab < dist_ac


# ============================================================================
# Tag colors
# ============================================================================

class TestTagColors:

    def test_known_tags_have_colors(self):
        for tag in CATEGORY_ORDER:
            assert tag in TAG_COLORS

    def test_custom_tag_gets_color(self):
        color = _tag_color("my_custom_tag")
        assert color.startswith("#")
        assert len(color) == 7

    def test_custom_tag_deterministic(self):
        assert _tag_color("custom") == _tag_color("custom")

    def test_known_tag_returns_fixed(self):
        assert _tag_color("identity") == "#e74c3c"


# ============================================================================
# Node radius
# ============================================================================

class TestNodeRadius:

    def test_min_confidence(self):
        assert _node_radius(0.0) == 8.0

    def test_max_confidence(self):
        assert _node_radius(1.0) == 24.0

    def test_mid_confidence(self):
        r = _node_radius(0.5)
        assert 8.0 < r < 24.0


# ============================================================================
# HTML escape
# ============================================================================

class TestHtmlEscape:

    def test_escapes_ampersand(self):
        assert "&amp;" in _html_escape("a & b")

    def test_escapes_angle_brackets(self):
        assert "&lt;" in _html_escape("<script>")
        assert "&gt;" in _html_escape("</script>")

    def test_plain_text_unchanged(self):
        assert _html_escape("hello") == "hello"


# ============================================================================
# HTML renderer
# ============================================================================

class TestRenderHTML:

    def _graph_and_layout(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.9))
        g.add_node(Node(id="n2", label="Healthcare", tags=["domain_knowledge"], confidence=0.7))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="applied_in"))
        layout = {"n1": (0.3, 0.4), "n2": (0.7, 0.6)}
        return g, layout

    def test_returns_valid_html(self):
        g, layout = self._graph_and_layout()
        html = render_html(g, layout)
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_nodes_in_output(self):
        g, layout = self._graph_and_layout()
        html = render_html(g, layout)
        assert "Python" in html
        assert "Healthcare" in html

    def test_edges_in_output(self):
        g, layout = self._graph_and_layout()
        html = render_html(g, layout)
        assert "applied_in" in html

    def test_self_contained(self):
        g, layout = self._graph_and_layout()
        html = render_html(g, layout)
        # No external resource references
        assert "http://" not in html
        assert "https://" not in html

    def test_legend_present(self):
        g, layout = self._graph_and_layout()
        html = render_html(g, layout)
        assert "technical_expertise" in html
        assert "domain_knowledge" in html

    def test_custom_dimensions(self):
        g, layout = self._graph_and_layout()
        html = render_html(g, layout, width=1200, height=900)
        assert "1200" in html
        assert "900" in html


# ============================================================================
# SVG renderer
# ============================================================================

class TestRenderSVG:

    def _graph_and_layout(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"], confidence=0.9))
        g.add_node(Node(id="n2", label="Health", tags=["domain"], confidence=0.7))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="uses"))
        layout = {"n1": (0.3, 0.4), "n2": (0.7, 0.6)}
        return g, layout

    def test_returns_valid_svg(self):
        g, layout = self._graph_and_layout()
        svg = render_svg(g, layout)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_circles_for_nodes(self):
        g, layout = self._graph_and_layout()
        svg = render_svg(g, layout)
        assert "<circle" in svg

    def test_lines_for_edges(self):
        g, layout = self._graph_and_layout()
        svg = render_svg(g, layout)
        assert "<line" in svg

    def test_text_labels(self):
        g, layout = self._graph_and_layout()
        svg = render_svg(g, layout)
        assert "Python" in svg
        assert "Health" in svg

    def test_edge_labels(self):
        g, layout = self._graph_and_layout()
        svg = render_svg(g, layout)
        assert "uses" in svg

    def test_custom_title(self):
        g, layout = self._graph_and_layout()
        svg = render_svg(g, layout, title="My Graph")
        assert "My Graph" in svg


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
