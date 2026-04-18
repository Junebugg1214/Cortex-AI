"""
Tests for Phase 4: Graph-Aware Deduplication

Covers:
- Text similarity (SequenceMatcher)
- Neighbor overlap (Jaccard)
- Combined similarity (weighted)
- Duplicate detection with tag pre-filter
- Greedy merge via CortexGraph.merge_nodes()
"""

import sys

from cortex.dedup import (
    combined_similarity,
    deduplicate,
    find_duplicates,
    neighbor_overlap,
    text_similarity,
)
from cortex.graph import CortexGraph, Edge, Node

# ============================================================================
# Text Similarity
# ============================================================================


class TestTextSimilarity:
    def test_identical_labels_score_1(self):
        assert text_similarity("Python", "Python") == 1.0

    def test_case_insensitive(self):
        assert text_similarity("Python", "python") == 1.0

    def test_completely_different_score_low(self):
        score = text_similarity("Python", "Healthcare")
        assert score < 0.5

    def test_partial_match_intermediate(self):
        score = text_similarity("Python", "Python programming")
        assert 0.4 < score < 1.0

    def test_very_similar_labels(self):
        score = text_similarity("Machine Learning", "Machine learning")
        assert score == 1.0


# ============================================================================
# Neighbor Overlap
# ============================================================================


class TestNeighborOverlap:
    def test_shared_neighbors_high_overlap(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_node(Node(id="c", label="C", tags=["t"]))
        # Both A and B connect to C
        g.add_edge(Edge(id="e1", source_id="a", target_id="c", relation="r"))
        g.add_edge(Edge(id="e2", source_id="b", target_id="c", relation="r"))
        overlap = neighbor_overlap(g, "a", "b")
        assert overlap == 1.0  # Both have only C as neighbor

    def test_no_shared_neighbors_zero(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        g.add_node(Node(id="c", label="C", tags=["t"]))
        g.add_node(Node(id="d", label="D", tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="c", relation="r"))
        g.add_edge(Edge(id="e2", source_id="b", target_id="d", relation="r"))
        overlap = neighbor_overlap(g, "a", "b")
        assert overlap == 0.0

    def test_both_isolated_returns_zero(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t"]))
        g.add_node(Node(id="b", label="B", tags=["t"]))
        overlap = neighbor_overlap(g, "a", "b")
        assert overlap == 0.0

    def test_partial_overlap(self):
        g = CortexGraph()
        for nid in ["a", "b", "c", "d"]:
            g.add_node(Node(id=nid, label=nid.upper(), tags=["t"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="c", relation="r"))
        g.add_edge(Edge(id="e2", source_id="a", target_id="d", relation="r"))
        g.add_edge(Edge(id="e3", source_id="b", target_id="c", relation="r"))
        # A neighbors: {c, d}, B neighbors: {c}. Intersection={c}, Union={c,d}
        overlap = neighbor_overlap(g, "a", "b")
        assert overlap == 0.5


# ============================================================================
# Combined Similarity
# ============================================================================


class TestCombinedSimilarity:
    def test_weights_applied_correctly(self):
        g = CortexGraph()
        a = Node(id="a", label="Python", tags=["t"])
        b = Node(id="b", label="Python", tags=["t"])
        g.add_node(a)
        g.add_node(b)
        # Identical labels (text_sim=1.0), no edges (neighbor_sim=0.0)
        sim = combined_similarity(g, a, b)
        # 0.7 * 1.0 + 0.3 * 0.0 = 0.7
        assert sim == 0.7

    def test_text_only_when_no_edges(self):
        g = CortexGraph()
        a = Node(id="a", label="Machine Learning", tags=["t"])
        b = Node(id="b", label="Machine learning systems", tags=["t"])
        g.add_node(a)
        g.add_node(b)
        sim = combined_similarity(g, a, b)
        # Only text component contributes
        assert 0.0 < sim < 1.0


# ============================================================================
# Find Duplicates
# ============================================================================


class TestFindDuplicates:
    def test_near_duplicate_labels_found(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["tech"]))
        g.add_node(Node(id="b", label="Python programming", tags=["tech"]))
        results = find_duplicates(g, threshold=0.3)
        assert len(results) >= 1
        assert results[0][0] == "a"
        assert results[0][1] == "b"

    def test_different_labels_not_matched(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["tech"]))
        g.add_node(Node(id="b", label="Healthcare", tags=["tech"]))
        results = find_duplicates(g, threshold=0.80)
        assert len(results) == 0

    def test_tag_overlap_filter(self):
        g = CortexGraph()
        # Identical labels but zero tag overlap — should not compare
        g.add_node(Node(id="a", label="Python", tags=["tech"]))
        g.add_node(Node(id="b", label="Python", tags=["domain"]))
        results = find_duplicates(g, threshold=0.5)
        assert len(results) == 0

    def test_threshold_respected(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["tech"]))
        g.add_node(Node(id="b", label="Python lang", tags=["tech"]))
        # Very high threshold — similarity might not meet it
        results = find_duplicates(g, threshold=0.99)
        assert len(results) == 0

    def test_sorted_by_similarity_desc(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["tech"]))
        g.add_node(Node(id="b", label="Python lang", tags=["tech"]))
        g.add_node(Node(id="c", label="Python programming", tags=["tech"]))
        results = find_duplicates(g, threshold=0.3)
        if len(results) >= 2:
            assert results[0][2] >= results[1][2]


# ============================================================================
# Deduplicate
# ============================================================================


class TestDeduplicate:
    def test_merge_executed_correctly(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["tech"], confidence=0.9))
        g.add_node(Node(id="b", label="Python programming", tags=["tech"], confidence=0.7))
        results = deduplicate(g, threshold=0.3)
        assert len(results) == 1
        assert results[0] == ("a", "b")
        # Node B should be merged into A
        assert g.get_node("b") is None
        assert g.get_node("a") is not None

    def test_already_merged_node_skipped(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["tech"]))
        g.add_node(Node(id="b", label="Python lang", tags=["tech"]))
        g.add_node(Node(id="c", label="Python code", tags=["tech"]))
        results = deduplicate(g, threshold=0.3)
        # Should not try to merge into a node that's already been merged away
        merged_ids = {r[1] for r in results}
        for survivor, merged in results:
            assert survivor not in merged_ids

    def test_empty_graph_no_crash(self):
        g = CortexGraph()
        results = deduplicate(g)
        assert results == []

    def test_no_duplicates_nothing_merged(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["tech"]))
        g.add_node(Node(id="b", label="Healthcare", tags=["tech"]))
        results = deduplicate(g, threshold=0.80)
        assert results == []

    def test_transitive_duplicates_merge_equivalence_class(self, monkeypatch):
        g = CortexGraph()
        g.add_node(
            Node(
                id="a",
                label="Alpha",
                tags=["tech"],
                confidence=0.70,
                first_seen="2026-03-01T00:00:00+00:00",
            )
        )
        g.add_node(
            Node(
                id="b",
                label="Beta",
                tags=["tech"],
                confidence=0.90,
                first_seen="2026-02-01T00:00:00+00:00",
            )
        )
        g.add_node(
            Node(
                id="c",
                label="Gamma",
                tags=["tech"],
                confidence=0.90,
                first_seen="2026-01-01T00:00:00+00:00",
            )
        )

        pairwise_similarity = {
            frozenset(("a", "b")): 0.82,
            frozenset(("b", "c")): 0.81,
            frozenset(("a", "c")): 0.65,
        }

        def fake_similarity(_graph, node_a, node_b, _text_weight=0.7, _neighbor_weight=0.3):
            return pairwise_similarity[frozenset((node_a.id, node_b.id))]

        monkeypatch.setattr("cortex.dedup.combined_similarity", fake_similarity)

        results = deduplicate(g, threshold=0.80)

        assert set(g.nodes) == {"c"}
        assert set(results) == {("c", "a"), ("c", "b")}
        assert g.get_node("c").confidence == 0.90
        assert g.get_node("c").first_seen == "2026-01-01T00:00:00+00:00"


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
