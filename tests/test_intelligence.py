"""
Tests for Cortex Phase 5: Intelligence Layer (v5.4)

Covers:
- GapAnalyzer: category_gaps, confidence_gaps, relationship_gaps,
  isolated_nodes, stale_nodes, all_gaps
- InsightGenerator: digest (comparing two graph snapshots)
"""

import sys
from datetime import datetime, timezone, timedelta

import pytest

from cortex.graph import CortexGraph, Node, Edge, CATEGORY_ORDER
from cortex.intelligence import GapAnalyzer, InsightGenerator


# ============================================================================
# GapAnalyzer.category_gaps
# ============================================================================

class TestCategoryGaps:

    def test_detects_missing_categories(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"]))
        analyzer = GapAnalyzer()
        gaps = analyzer.category_gaps(g)
        gap_cats = {gap["category"] for gap in gaps}
        assert "identity" in gap_cats
        assert "technical_expertise" not in gap_cats

    def test_no_gaps_when_all_present(self):
        g = CortexGraph()
        for i, cat in enumerate(CATEGORY_ORDER):
            g.add_node(Node(id=str(i), label=f"N{i}", tags=[cat]))
        analyzer = GapAnalyzer()
        assert analyzer.category_gaps(g) == []

    def test_empty_graph_all_gaps(self):
        analyzer = GapAnalyzer()
        gaps = analyzer.category_gaps(CortexGraph())
        assert len(gaps) == len(CATEGORY_ORDER)

    def test_custom_tags_not_flagged(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="X", tags=["custom_tag"]))
        analyzer = GapAnalyzer()
        gaps = analyzer.category_gaps(g)
        gap_cats = {gap["category"] for gap in gaps}
        assert "custom_tag" not in gap_cats


# ============================================================================
# GapAnalyzer.confidence_gaps
# ============================================================================

class TestConfidenceGaps:

    def test_low_confidence_priorities_detected(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Build CLI", tags=["active_priorities"], confidence=0.4))
        analyzer = GapAnalyzer()
        gaps = analyzer.confidence_gaps(g)
        assert len(gaps) == 1
        assert gaps[0]["label"] == "Build CLI"

    def test_high_confidence_not_flagged(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Build CLI", tags=["active_priorities"], confidence=0.9))
        analyzer = GapAnalyzer()
        assert analyzer.confidence_gaps(g) == []

    def test_non_priority_not_flagged(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.3))
        analyzer = GapAnalyzer()
        assert analyzer.confidence_gaps(g) == []

    def test_custom_threshold(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Goal", tags=["active_priorities"], confidence=0.7))
        analyzer = GapAnalyzer()
        assert analyzer.confidence_gaps(g, threshold=0.6) == []
        assert len(analyzer.confidence_gaps(g, threshold=0.8)) == 1


# ============================================================================
# GapAnalyzer.relationship_gaps
# ============================================================================

class TestRelationshipGaps:

    def test_nodes_without_edges_detected(self):
        g = CortexGraph()
        for i in range(4):
            g.add_node(Node(id=str(i), label=f"Biz{i}", tags=["business_context"]))
        analyzer = GapAnalyzer()
        gaps = analyzer.relationship_gaps(g)
        assert len(gaps) == 1
        assert gaps[0]["tag"] == "business_context"

    def test_nodes_with_edges_no_gap(self):
        g = CortexGraph()
        for i in range(3):
            g.add_node(Node(id=str(i), label=f"Biz{i}", tags=["business_context"]))
        g.add_edge(Edge(id="e1", source_id="0", target_id="1", relation="r"))
        analyzer = GapAnalyzer()
        assert analyzer.relationship_gaps(g) == []

    def test_small_group_not_flagged(self):
        g = CortexGraph()
        g.add_node(Node(id="0", label="B0", tags=["business_context"]))
        g.add_node(Node(id="1", label="B1", tags=["business_context"]))
        analyzer = GapAnalyzer()
        assert analyzer.relationship_gaps(g) == []


# ============================================================================
# GapAnalyzer.isolated_nodes
# ============================================================================

class TestIsolatedNodes:

    def test_isolated_detected(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Alone", tags=["t"], confidence=0.8))
        g.add_node(Node(id="b", label="Connected", tags=["t"], confidence=0.5))
        g.add_node(Node(id="c", label="Also", tags=["t"], confidence=0.3))
        g.add_edge(Edge(id="e1", source_id="b", target_id="c", relation="r"))
        analyzer = GapAnalyzer()
        isolated = analyzer.isolated_nodes(g)
        assert len(isolated) == 1
        assert isolated[0].label == "Alone"

    def test_connected_not_isolated(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        analyzer = GapAnalyzer()
        assert analyzer.isolated_nodes(g) == []

    def test_all_connected_empty(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        analyzer = GapAnalyzer()
        assert analyzer.isolated_nodes(g) == []

    def test_sorted_by_confidence(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Low", tags=["t"], confidence=0.2))
        g.add_node(Node(id="b", label="High", tags=["t"], confidence=0.9))
        analyzer = GapAnalyzer()
        isolated = analyzer.isolated_nodes(g)
        assert isolated[0].label == "High"


# ============================================================================
# GapAnalyzer.stale_nodes
# ============================================================================

class TestStaleNodes:

    def test_stale_detected(self):
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Old", tags=["t"], last_seen=old_date))
        analyzer = GapAnalyzer()
        stale = analyzer.stale_nodes(g, days=180)
        assert len(stale) == 1

    def test_recent_not_stale(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Recent", tags=["t"], last_seen=recent))
        analyzer = GapAnalyzer()
        assert analyzer.stale_nodes(g, days=180) == []

    def test_recent_snapshot_not_stale(self):
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        g = CortexGraph()
        g.add_node(Node(
            id="n1", label="Snapped", tags=["t"], last_seen=old_date,
            snapshots=[{"timestamp": recent, "source": "manual"}],
        ))
        analyzer = GapAnalyzer()
        assert analyzer.stale_nodes(g, days=180) == []

    def test_no_timestamps_not_stale(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="No TS", tags=["t"]))
        analyzer = GapAnalyzer()
        assert analyzer.stale_nodes(g) == []

    def test_custom_days(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Semi", tags=["t"], last_seen=recent))
        analyzer = GapAnalyzer()
        assert analyzer.stale_nodes(g, days=180) == []
        assert len(analyzer.stale_nodes(g, days=30)) == 1


# ============================================================================
# GapAnalyzer.all_gaps
# ============================================================================

class TestAllGaps:

    def test_returns_all_sections(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"]))
        analyzer = GapAnalyzer()
        gaps = analyzer.all_gaps(g)
        assert "category_gaps" in gaps
        assert "confidence_gaps" in gaps
        assert "relationship_gaps" in gaps
        assert "isolated_nodes" in gaps
        assert "stale_nodes" in gaps

    def test_empty_graph(self):
        analyzer = GapAnalyzer()
        gaps = analyzer.all_gaps(CortexGraph())
        assert len(gaps["category_gaps"]) == len(CATEGORY_ORDER)
        assert gaps["confidence_gaps"] == []
        assert gaps["relationship_gaps"] == []
        assert gaps["isolated_nodes"] == []
        assert gaps["stale_nodes"] == []


# ============================================================================
# InsightGenerator.digest
# ============================================================================

class TestInsightDigest:

    def _graph_a(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"], confidence=0.9))
        g.add_node(Node(id="n2", label="Healthcare", tags=["domain"], confidence=0.7))
        g.add_node(Node(id="n3", label="Old Topic", tags=["tech"], confidence=0.5))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="applied_in"))
        return g

    def _graph_b(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"], confidence=0.6))
        g.add_node(Node(id="n2", label="Healthcare", tags=["domain"], confidence=0.7))
        g.add_node(Node(id="n4", label="New Topic", tags=["tech"], confidence=0.8))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="applied_in"))
        g.add_edge(Edge(id="e2", source_id="n1", target_id="n4", relation="uses"))
        return g

    def test_new_nodes_detected(self):
        gen = InsightGenerator()
        digest = gen.digest(current=self._graph_b(), previous=self._graph_a())
        new_labels = {n["label"] for n in digest["new_nodes"]}
        assert "New Topic" in new_labels

    def test_removed_nodes_detected(self):
        gen = InsightGenerator()
        digest = gen.digest(current=self._graph_b(), previous=self._graph_a())
        removed_labels = {n["label"] for n in digest["removed_nodes"]}
        assert "Old Topic" in removed_labels

    def test_confidence_change_detected(self):
        gen = InsightGenerator()
        digest = gen.digest(current=self._graph_b(), previous=self._graph_a())
        # Python: 0.9 → 0.6, delta = -0.3
        changes = {c["label"]: c["delta"] for c in digest["confidence_changes"]}
        assert "Python" in changes
        assert changes["Python"] == pytest.approx(-0.3, abs=0.01)

    def test_small_change_ignored(self):
        g1 = CortexGraph()
        g1.add_node(Node(id="n1", label="X", tags=["t"], confidence=0.5))
        g2 = CortexGraph()
        g2.add_node(Node(id="n1", label="X", tags=["t"], confidence=0.6))
        gen = InsightGenerator()
        digest = gen.digest(current=g2, previous=g1)
        assert len(digest["confidence_changes"]) == 0  # delta=0.1 < 0.2

    def test_new_edges_detected(self):
        gen = InsightGenerator()
        digest = gen.digest(current=self._graph_b(), previous=self._graph_a())
        new_edge_rels = {e["relation"] for e in digest["new_edges"]}
        assert "uses" in new_edge_rels

    def test_drift_score_included(self):
        gen = InsightGenerator()
        digest = gen.digest(current=self._graph_b(), previous=self._graph_a())
        assert "drift_score" in digest
        assert "score" in digest["drift_score"] or "sufficient_data" in digest["drift_score"]

    def test_contradictions_included(self):
        gen = InsightGenerator()
        digest = gen.digest(current=self._graph_b(), previous=self._graph_a())
        assert "new_contradictions" in digest
        assert isinstance(digest["new_contradictions"], list)

    def test_gaps_included(self):
        gen = InsightGenerator()
        digest = gen.digest(current=self._graph_b(), previous=self._graph_a())
        assert "gaps" in digest
        assert "category_gaps" in digest["gaps"]

    def test_empty_graphs(self):
        gen = InsightGenerator()
        digest = gen.digest(current=CortexGraph(), previous=CortexGraph())
        assert digest["new_nodes"] == []
        assert digest["removed_nodes"] == []
        assert digest["confidence_changes"] == []
        assert digest["new_edges"] == []


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
