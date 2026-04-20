"""
Tests for Cortex Phase 5: Query Engine + Graph Algorithms (v5.4)

Covers:
- QueryEngine: query_category, query_path, query_changed, query_related,
  query_strongest, query_weakest
- NL syntactic sugar: parse_nl_query
- Graph algorithms: shortest_path, connected_components, betweenness_centrality
"""

import sys

import pytest

from cortex.graph.graph import CortexGraph, Edge, Node
from cortex.graph.query import (
    QueryEngine,
    betweenness_centrality,
    connected_components,
    parse_nl_query,
    shortest_path,
)

# ============================================================================
# Helpers
# ============================================================================


def _chain_graph():
    """A -> B -> C -> D linear chain."""
    g = CortexGraph()
    for nid, label, tag in [("a", "A", "t1"), ("b", "B", "t1"), ("c", "C", "t2"), ("d", "D", "t2")]:
        g.add_node(Node(id=nid, label=label, tags=[tag], confidence=0.5))
    g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
    g.add_edge(Edge(id="e2", source_id="b", target_id="c", relation="r"))
    g.add_edge(Edge(id="e3", source_id="c", target_id="d", relation="r"))
    return g


def _disconnected_graph():
    """Two clusters: {A,B} and {C,D} with an isolated node E."""
    g = CortexGraph()
    for nid, label in [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"), ("e", "E")]:
        g.add_node(Node(id=nid, label=label, tags=["t"], confidence=0.5))
    g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
    g.add_edge(Edge(id="e2", source_id="c", target_id="d", relation="r"))
    return g


# ============================================================================
# QueryEngine.query_category
# ============================================================================


class TestQueryCategory:
    def test_returns_matching_nodes(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"], confidence=0.9))
        g.add_node(Node(id="n2", label="JS", tags=["tech"], confidence=0.7))
        g.add_node(Node(id="n3", label="Health", tags=["domain"], confidence=0.8))
        engine = QueryEngine(g)
        result = engine.query_category("tech")
        assert len(result) == 2
        assert result[0].label == "Python"  # highest confidence first

    def test_empty_for_missing_tag(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"]))
        engine = QueryEngine(g)
        assert engine.query_category("nonexistent") == []

    def test_sorted_by_confidence(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="A", tags=["t"], confidence=0.3))
        g.add_node(Node(id="n2", label="B", tags=["t"], confidence=0.9))
        g.add_node(Node(id="n3", label="C", tags=["t"], confidence=0.6))
        engine = QueryEngine(g)
        result = engine.query_category("t")
        confs = [n.confidence for n in result]
        assert confs == sorted(confs, reverse=True)

    def test_multi_tag_node(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech", "domain"]))
        engine = QueryEngine(g)
        assert len(engine.query_category("tech")) == 1
        assert len(engine.query_category("domain")) == 1

    def test_empty_graph(self):
        engine = QueryEngine(CortexGraph())
        assert engine.query_category("any") == []


# ============================================================================
# QueryEngine.query_path
# ============================================================================


class TestQueryPath:
    def test_direct_neighbors(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        paths = engine.query_path("A", "B")
        assert len(paths) == 1
        assert [n.label for n in paths[0]] == ["A", "B"]

    def test_two_hops(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        paths = engine.query_path("A", "C")
        assert len(paths) == 1
        assert [n.label for n in paths[0]] == ["A", "B", "C"]

    def test_no_connection(self):
        g = _disconnected_graph()
        engine = QueryEngine(g)
        assert engine.query_path("A", "C") == []

    def test_source_not_found(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        assert engine.query_path("Nonexistent", "A") == []

    def test_target_not_found(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        assert engine.query_path("A", "Nonexistent") == []

    def test_same_node(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        paths = engine.query_path("A", "A")
        assert len(paths) == 1
        assert paths[0][0].label == "A"


# ============================================================================
# QueryEngine.query_changed
# ============================================================================


class TestQueryChanged:
    def test_finds_new_nodes(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="New", tags=["t"], first_seen="2025-06-01"))
        g.add_node(Node(id="n2", label="Old", tags=["t"], first_seen="2024-01-01"))
        engine = QueryEngine(g)
        result = engine.query_changed("2025-05-01")
        assert len(result["new_nodes"]) == 1
        assert result["new_nodes"][0]["label"] == "New"

    def test_finds_updated_nodes(self):
        g = CortexGraph()
        g.add_node(
            Node(
                id="n1",
                label="Updated",
                tags=["t"],
                first_seen="2024-01-01",
                last_seen="2025-06-15",
            )
        )
        engine = QueryEngine(g)
        result = engine.query_changed("2025-05-01")
        assert len(result["updated_nodes"]) == 1

    def test_excludes_old_nodes(self):
        g = CortexGraph()
        g.add_node(
            Node(
                id="n1",
                label="Old",
                tags=["t"],
                first_seen="2024-01-01",
                last_seen="2024-06-01",
            )
        )
        engine = QueryEngine(g)
        result = engine.query_changed("2025-01-01")
        assert result["total_changed"] == 0

    def test_empty_graph(self):
        engine = QueryEngine(CortexGraph())
        result = engine.query_changed("2025-01-01")
        assert result["total_changed"] == 0

    def test_snapshot_timestamp_counted(self):
        g = CortexGraph()
        g.add_node(
            Node(
                id="n1",
                label="Snapped",
                tags=["t"],
                first_seen="2024-01-01",
                last_seen="2024-06-01",
                snapshots=[{"timestamp": "2025-07-01", "source": "manual"}],
            )
        )
        engine = QueryEngine(g)
        result = engine.query_changed("2025-05-01")
        assert len(result["updated_nodes"]) == 1

    def test_validity_timestamp_counted(self):
        g = CortexGraph()
        g.add_node(
            Node(
                id="n1",
                label="Planned launch",
                tags=["active_priorities"],
                first_seen="2024-01-01",
                valid_from="2025-07-01T00:00:00Z",
            )
        )
        engine = QueryEngine(g)
        result = engine.query_changed("2025-05-01")
        assert len(result["updated_nodes"]) == 1


# ============================================================================
# QueryEngine.query_related
# ============================================================================


class TestQueryRelated:
    def test_depth_1(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        result = engine.query_related("B", depth=1)
        labels = {n.label for n in result}
        assert labels == {"A", "C"}

    def test_depth_2(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        result = engine.query_related("A", depth=2)
        labels = {n.label for n in result}
        assert "B" in labels
        assert "C" in labels

    def test_excludes_seed(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        result = engine.query_related("A", depth=3)
        labels = {n.label for n in result}
        assert "A" not in labels

    def test_nonexistent_label(self):
        g = _chain_graph()
        engine = QueryEngine(g)
        assert engine.query_related("Nope") == []


# ============================================================================
# QueryEngine.query_strongest / query_weakest
# ============================================================================


class TestQueryStrongestWeakest:
    def test_strongest_returns_top_n(self):
        g = CortexGraph()
        for i in range(5):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"], confidence=i * 0.2))
        engine = QueryEngine(g)
        result = engine.query_strongest(3)
        assert len(result) == 3
        assert result[0].confidence >= result[1].confidence

    def test_weakest_returns_bottom_n(self):
        g = CortexGraph()
        for i in range(5):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"], confidence=i * 0.2))
        engine = QueryEngine(g)
        result = engine.query_weakest(3)
        assert len(result) == 3
        assert result[0].confidence <= result[1].confidence

    def test_strongest_n_larger_than_graph(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"], confidence=0.5))
        engine = QueryEngine(g)
        result = engine.query_strongest(100)
        assert len(result) == 1

    def test_weakest_empty_graph(self):
        engine = QueryEngine(CortexGraph())
        assert engine.query_weakest(10) == []


# ============================================================================
# NL Query Parser
# ============================================================================


class TestNLQuery:
    def _engine(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.9))
        g.add_node(Node(id="n2", label="Healthcare", tags=["domain"], confidence=0.8))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="applied_in"))
        return QueryEngine(g)

    def test_what_are_my_tag(self):
        result = parse_nl_query("what are my technical_expertise", self._engine())
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["label"] == "Python"

    def test_how_does_relate(self):
        result = parse_nl_query("how does Python relate to Healthcare", self._engine())
        assert isinstance(result, dict)
        assert result["found"] is True
        assert len(result["path"]) == 2

    def test_what_changed_since(self):
        result = parse_nl_query("what changed since 2020-01-01", self._engine())
        assert isinstance(result, dict)
        assert "total_changed" in result

    def test_unrecognized_query(self):
        result = parse_nl_query("do something random", self._engine())
        assert isinstance(result, str)
        assert "not recognized" in result.lower()

    def test_case_insensitive(self):
        result = parse_nl_query("What Are My technical_expertise", self._engine())
        assert isinstance(result, list)


# ============================================================================
# shortest_path (BFS)
# ============================================================================


class TestShortestPath:
    def test_direct_path(self):
        g = _chain_graph()
        assert shortest_path(g, "a", "b") == ["a", "b"]

    def test_multi_hop(self):
        g = _chain_graph()
        path = shortest_path(g, "a", "d")
        assert path == ["a", "b", "c", "d"]

    def test_no_path(self):
        g = _disconnected_graph()
        assert shortest_path(g, "a", "c") == []

    def test_same_node(self):
        g = _chain_graph()
        assert shortest_path(g, "a", "a") == ["a"]

    def test_nonexistent_node(self):
        g = _chain_graph()
        assert shortest_path(g, "a", "z") == []

    def test_shortest_among_multiple(self):
        g = CortexGraph()
        for nid in ["a", "b", "c"]:
            g.add_node(Node(id=nid, label=nid.upper(), tags=["t"]))
        # Direct A-C and indirect A-B-C
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        g.add_edge(Edge(id="e2", source_id="b", target_id="c", relation="r"))
        g.add_edge(Edge(id="e3", source_id="a", target_id="c", relation="r"))
        path = shortest_path(g, "a", "c")
        assert len(path) == 2  # Direct path is shorter


# ============================================================================
# connected_components (union-find)
# ============================================================================


class TestConnectedComponents:
    def test_single_component(self):
        g = _chain_graph()
        comps = connected_components(g)
        assert len(comps) == 1
        assert len(comps[0]) == 4

    def test_two_components(self):
        g = _disconnected_graph()
        comps = connected_components(g)
        # {A,B}, {C,D}, {E}
        assert len(comps) == 3

    def test_isolated_nodes_are_components(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        comps = connected_components(g)
        assert len(comps) == 2

    def test_empty_graph(self):
        assert connected_components(CortexGraph()) == []

    def test_sorted_by_size(self):
        g = _disconnected_graph()
        comps = connected_components(g)
        sizes = [len(c) for c in comps]
        assert sizes == sorted(sizes, reverse=True)


# ============================================================================
# betweenness_centrality (Brandes)
# ============================================================================


class TestBetweennessCentrality:
    def test_skips_small_graphs(self):
        g = _chain_graph()
        assert betweenness_centrality(g) == {}

    def _linear_50(self):
        g = CortexGraph()
        for i in range(50):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"]))
        for i in range(49):
            g.add_edge(Edge(id=f"e{i}", source_id=str(i), target_id=str(i + 1), relation="r"))
        return g

    def test_bridge_node_highest(self):
        g = self._linear_50()
        scores = betweenness_centrality(g)
        assert len(scores) == 50
        # Middle node (24 or 25) should have highest betweenness
        mid = max(scores, key=scores.get)
        assert int(mid) in range(20, 30)  # approximately middle

    def test_scores_are_normalized(self):
        g = self._linear_50()
        scores = betweenness_centrality(g)
        assert all(0.0 <= s <= 1.0 for s in scores.values())


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
