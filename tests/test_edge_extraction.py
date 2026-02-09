"""
Tests for Phase 4: Edge Extraction + Centrality

Covers:
- ExtractionRule dataclass
- Rule-based edge discovery (tag pair matching)
- Proximity-based edge discovery (co_mentioned)
- Combined discovery with dedup
- Degree centrality
- PageRank convergence
- Centrality dispatch
- Confidence boost
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cortex.graph import CortexGraph, Node, Edge, make_edge_id
from cortex.edge_extraction import (
    ExtractionRule,
    CATEGORY_PAIR_RULES,
    extract_edges_by_rules,
    extract_edges_by_proximity,
    discover_all_edges,
)
from cortex.centrality import (
    compute_degree_centrality,
    compute_pagerank,
    compute_centrality,
    apply_centrality_boost,
)


# ============================================================================
# ExtractionRule
# ============================================================================

class TestExtractionRule:

    def test_dataclass_fields(self):
        r = ExtractionRule("tech", "priorities", "used_in", 0.6)
        assert r.source_tag == "tech"
        assert r.target_tag == "priorities"
        assert r.relation == "used_in"
        assert r.confidence == 0.6

    def test_category_pair_rules_count(self):
        assert len(CATEGORY_PAIR_RULES) == 8


# ============================================================================
# Rule-Based Extraction
# ============================================================================

class TestRuleBasedExtraction:

    def _graph_with_tagged_nodes(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"]))
        g.add_node(Node(id="n2", label="Build CLI Tool", tags=["active_priorities"]))
        g.add_node(Node(id="n3", label="Marc", tags=["identity"]))
        g.add_node(Node(id="n4", label="Acme Corp", tags=["business_context"]))
        return g

    def test_single_rule_creates_edges(self):
        g = self._graph_with_tagged_nodes()
        rules = [ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6)]
        edges = extract_edges_by_rules(g, rules)
        assert len(edges) == 1
        assert edges[0].source_id == "n1"
        assert edges[0].target_id == "n2"
        assert edges[0].relation == "used_in"
        assert edges[0].confidence == 0.6

    def test_no_match_when_tags_missing(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"]))
        # No node with "active_priorities"
        rules = [ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6)]
        edges = extract_edges_by_rules(g, rules)
        assert len(edges) == 0

    def test_multiple_rules_all_fire(self):
        g = self._graph_with_tagged_nodes()
        rules = [
            ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6),
            ExtractionRule("identity", "business_context", "works_at", 0.7),
        ]
        edges = extract_edges_by_rules(g, rules)
        relations = {e.relation for e in edges}
        assert "used_in" in relations
        assert "works_at" in relations

    def test_no_duplicate_edges(self):
        g = self._graph_with_tagged_nodes()
        rules = [ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6)]
        edges1 = extract_edges_by_rules(g, rules)
        # Add first batch to graph
        for e in edges1:
            g.add_edge(e)
        # Run again — should find nothing new
        edges2 = extract_edges_by_rules(g, rules)
        assert len(edges2) == 0

    def test_existing_edge_not_recreated(self):
        g = self._graph_with_tagged_nodes()
        # Pre-add an edge
        g.add_edge(Edge(
            id=make_edge_id("n1", "n2", "used_in"),
            source_id="n1", target_id="n2", relation="used_in",
            confidence=0.9,
        ))
        rules = [ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6)]
        edges = extract_edges_by_rules(g, rules)
        assert len(edges) == 0

    def test_custom_rules_override_defaults(self):
        g = self._graph_with_tagged_nodes()
        custom = [ExtractionRule("identity", "business_context", "employed_by", 0.8)]
        edges = extract_edges_by_rules(g, custom)
        assert len(edges) == 1
        assert edges[0].relation == "employed_by"

    def test_self_loop_prevented(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise", "active_priorities"]))
        rules = [ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6)]
        edges = extract_edges_by_rules(g, rules)
        assert len(edges) == 0

    def test_default_rules_used_when_none(self):
        g = self._graph_with_tagged_nodes()
        edges = extract_edges_by_rules(g)
        # Should use CATEGORY_PAIR_RULES — at least tech→priorities and identity→business
        assert len(edges) >= 2


# ============================================================================
# Proximity Extraction
# ============================================================================

class TestProximityExtraction:

    def _graph_with_nodes(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"]))
        g.add_node(Node(id="n2", label="Healthcare", tags=["domain"]))
        g.add_node(Node(id="n3", label="Machine Learning", tags=["tech"]))
        return g

    def test_nearby_labels_create_edge(self):
        g = self._graph_with_nodes()
        messages = ["I use Python for Healthcare data analysis"]
        edges = extract_edges_by_proximity(g, messages)
        assert len(edges) >= 1
        pairs = {(e.source_id, e.target_id) for e in edges}
        # Python and Healthcare are within 200 chars
        assert ("n1", "n2") in pairs or ("n2", "n1") in pairs

    def test_distant_labels_no_edge(self):
        g = self._graph_with_nodes()
        filler = "x" * 300
        messages = [f"Python {filler} Healthcare"]
        edges = extract_edges_by_proximity(g, messages)
        # Python and Healthcare are > 200 chars apart
        pairs = {(e.source_id, e.target_id) for e in edges}
        assert ("n1", "n2") not in pairs and ("n2", "n1") not in pairs

    def test_same_node_no_self_loop(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"]))
        messages = ["Python is great. I love Python so much."]
        edges = extract_edges_by_proximity(g, messages)
        assert len(edges) == 0

    def test_confidence_is_0_3(self):
        g = self._graph_with_nodes()
        messages = ["Python and Healthcare together"]
        edges = extract_edges_by_proximity(g, messages)
        for e in edges:
            assert e.confidence == 0.3

    def test_co_mentioned_relation(self):
        g = self._graph_with_nodes()
        messages = ["Python and Healthcare"]
        edges = extract_edges_by_proximity(g, messages)
        for e in edges:
            assert e.relation == "co_mentioned"

    def test_empty_messages_no_crash(self):
        g = self._graph_with_nodes()
        edges = extract_edges_by_proximity(g, [])
        assert edges == []

    def test_existing_edge_skipped(self):
        g = self._graph_with_nodes()
        g.add_edge(Edge(
            id="e1", source_id="n1", target_id="n2",
            relation="related_to", confidence=0.8,
        ))
        messages = ["Python and Healthcare"]
        edges = extract_edges_by_proximity(g, messages)
        # n1-n2 already connected — should not create another
        pairs = {(e.source_id, e.target_id) for e in edges}
        assert ("n1", "n2") not in pairs and ("n2", "n1") not in pairs


# ============================================================================
# Combined Discovery
# ============================================================================

class TestDiscoverAllEdges:

    def test_rules_plus_proximity_combined(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"]))
        g.add_node(Node(id="n2", label="Build App", tags=["active_priorities"]))
        # "Yoga" has a tag that no rule covers, so only proximity can create an edge
        g.add_node(Node(id="n3", label="Yoga", tags=["personal_interests"]))
        messages = ["Python and Yoga are both part of my routine"]
        edges = discover_all_edges(g, messages=messages)
        relations = {e.relation for e in edges}
        assert "used_in" in relations  # rule-based (n1→n2)
        assert "co_mentioned" in relations  # proximity-based (n1↔n3)

    def test_rule_edge_takes_priority(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"]))
        g.add_node(Node(id="n2", label="Build App", tags=["active_priorities"]))
        messages = ["Python Build App mentioned together"]
        edges = discover_all_edges(g, messages=messages)
        # Rule covers n1→n2 with used_in; proximity should NOT add co_mentioned for same pair
        edge_for_pair = [e for e in edges if {e.source_id, e.target_id} == {"n1", "n2"}]
        assert len(edge_for_pair) == 1
        assert edge_for_pair[0].relation == "used_in"

    def test_empty_graph_no_crash(self):
        g = CortexGraph()
        edges = discover_all_edges(g)
        assert edges == []

    def test_no_messages_only_rules(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"]))
        g.add_node(Node(id="n2", label="Build App", tags=["active_priorities"]))
        edges = discover_all_edges(g, messages=None)
        assert len(edges) >= 1
        assert all(e.relation != "co_mentioned" for e in edges)


# ============================================================================
# Degree Centrality
# ============================================================================

class TestDegreeCentrality:

    def test_hub_node_highest_centrality(self):
        g = CortexGraph()
        g.add_node(Node(id="hub", label="Hub", tags=["t"]))
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_node(Node(id="c", label="C", tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="hub", target_id="a", relation="r"))
        g.add_edge(Edge(id="e2", source_id="hub", target_id="b", relation="r"))
        g.add_edge(Edge(id="e3", source_id="hub", target_id="c", relation="r"))
        scores = compute_degree_centrality(g)
        assert scores["hub"] == 1.0  # 3 edges / (4-1)
        assert scores["a"] == pytest.approx(1 / 3)

    def test_isolated_node_zero_centrality(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        scores = compute_degree_centrality(g)
        assert scores["a"] == 0.0
        assert scores["b"] == 0.0

    def test_single_node(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        scores = compute_degree_centrality(g)
        assert scores["a"] == 0.0


# ============================================================================
# PageRank
# ============================================================================

class TestPageRank:

    def test_convergence_on_small_graph(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_node(Node(id="c", label="C", tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        g.add_edge(Edge(id="e2", source_id="b", target_id="c", relation="r"))
        g.add_edge(Edge(id="e3", source_id="c", target_id="a", relation="r"))
        scores = compute_pagerank(g)
        # Cycle → all scores should be roughly equal
        for s in scores.values():
            assert s == pytest.approx(1 / 3, abs=0.01)

    def test_scores_sum_to_one(self):
        g = CortexGraph()
        for i in range(5):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"]))
        g.add_edge(Edge(id="e0", source_id="0", target_id="1", relation="r"))
        g.add_edge(Edge(id="e1", source_id="1", target_id="2", relation="r"))
        g.add_edge(Edge(id="e2", source_id="2", target_id="0", relation="r"))
        g.add_edge(Edge(id="e3", source_id="3", target_id="4", relation="r"))
        scores = compute_pagerank(g)
        assert sum(scores.values()) == pytest.approx(1.0, abs=0.01)

    def test_empty_graph(self):
        g = CortexGraph()
        scores = compute_pagerank(g)
        assert scores == {}


# ============================================================================
# Centrality Dispatch
# ============================================================================

class TestCentralityDispatch:

    def test_small_graph_uses_degree(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        scores = compute_centrality(g)
        # Degree centrality: each has 1 edge / (2-1) = 1.0
        assert scores["a"] == 1.0
        assert scores["b"] == 1.0


# ============================================================================
# Centrality Boost
# ============================================================================

class TestCentralityBoost:

    def _graph_with_20_nodes(self):
        g = CortexGraph()
        for i in range(20):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"], confidence=0.5))
        # Hub: node 0 connects to all others
        for i in range(1, 20):
            g.add_edge(Edge(id=f"e{i}", source_id="0", target_id=str(i), relation="r"))
        return g

    def test_top_decile_gets_boost(self):
        g = self._graph_with_20_nodes()
        scores = compute_centrality(g)
        original = g.get_node("0").confidence
        apply_centrality_boost(g, scores)
        assert g.get_node("0").confidence > original

    def test_confidence_capped_at_1(self):
        g = CortexGraph()
        for i in range(20):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"], confidence=0.99))
        for i in range(1, 20):
            g.add_edge(Edge(id=f"e{i}", source_id="0", target_id=str(i), relation="r"))
        scores = compute_centrality(g)
        apply_centrality_boost(g, scores)
        assert g.get_node("0").confidence <= 1.0

    def test_fewer_than_20_nodes_no_boost(self):
        g = CortexGraph()
        for i in range(5):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=["t"], confidence=0.5))
        g.add_edge(Edge(id="e1", source_id="0", target_id="1", relation="r"))
        scores = compute_centrality(g)
        apply_centrality_boost(g, scores)
        # Confidence should stay at 0.5 (no boost applied)
        assert g.get_node("0").confidence == 0.5

    def test_centrality_stored_in_properties(self):
        g = self._graph_with_20_nodes()
        scores = compute_centrality(g)
        apply_centrality_boost(g, scores)
        assert "centrality" in g.get_node("0").properties
        assert g.get_node("0").properties["centrality"] > 0


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
