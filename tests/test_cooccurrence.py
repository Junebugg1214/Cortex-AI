"""
Tests for Phase 4: Co-Occurrence Edge Discovery

Covers:
- Co-occurrence counting (message-level)
- Label message counts
- PMI edge scoring
- Frequency edge scoring
- Tiered dispatch (PMI >= 500, frequency >= 100, strict < 100)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cortex.graph import CortexGraph, Node, Edge
from cortex.cooccurrence import (
    count_cooccurrences,
    label_message_counts,
    pmi_edges,
    frequency_edges,
    discover_edges,
)


# ============================================================================
# Counting
# ============================================================================

class TestCountCooccurrences:

    def test_basic_cooccurrence_count(self):
        messages = [
            "Python and Healthcare",
            "Python and Machine Learning",
            "Python and Healthcare again",
        ]
        labels = ["Python", "Healthcare", "Machine Learning"]
        counts = count_cooccurrences(messages, labels)
        assert counts[("Healthcare", "Python")] == 2
        assert counts[("Machine Learning", "Python")] == 1

    def test_case_insensitive_matching(self):
        messages = ["python and HEALTHCARE"]
        labels = ["Python", "Healthcare"]
        counts = count_cooccurrences(messages, labels)
        assert counts[("Healthcare", "Python")] == 1

    def test_no_occurrences_no_entries(self):
        messages = ["nothing relevant here"]
        labels = ["Python", "Healthcare"]
        counts = count_cooccurrences(messages, labels)
        assert len(counts) == 0

    def test_single_message_single_pair(self):
        messages = ["Python Healthcare"]
        labels = ["Python", "Healthcare"]
        counts = count_cooccurrences(messages, labels)
        assert len(counts) == 1

    def test_empty_messages(self):
        counts = count_cooccurrences([], ["Python"])
        assert len(counts) == 0


class TestLabelMessageCounts:

    def test_basic_counts(self):
        messages = ["Python is great", "Python again", "Healthcare only"]
        labels = ["Python", "Healthcare"]
        counts = label_message_counts(messages, labels)
        assert counts["Python"] == 2
        assert counts["Healthcare"] == 1

    def test_zero_for_absent_label(self):
        messages = ["nothing here"]
        labels = ["Python"]
        counts = label_message_counts(messages, labels)
        assert counts["Python"] == 0


# ============================================================================
# PMI
# ============================================================================

class TestPMI:

    def test_pmi_high_for_exclusive_cooccurrence(self):
        # A and B always appear together, never apart
        cooc = {("A", "B"): 10}
        label_counts = {"A": 10, "B": 10}
        total = 100
        results = pmi_edges(cooc, label_counts, total, threshold=0.0, min_count=3)
        assert len(results) == 1
        assert results[0][2] > 0  # PMI should be positive

    def test_pmi_low_for_common_labels(self):
        # Both appear in all messages, co-occur at random rate
        cooc = {("A", "B"): 50}
        label_counts = {"A": 100, "B": 100}
        total = 100
        results = pmi_edges(cooc, label_counts, total, threshold=2.0, min_count=3)
        # P(A,B) = 0.5, P(A)*P(B) = 1.0, PMI = log2(0.5) < 0
        assert len(results) == 0

    def test_min_count_filter(self):
        cooc = {("A", "B"): 2}  # Below min_count=3
        label_counts = {"A": 5, "B": 5}
        results = pmi_edges(cooc, label_counts, 100, threshold=0.0, min_count=3)
        assert len(results) == 0

    def test_threshold_filter(self):
        cooc = {("A", "B"): 5}
        label_counts = {"A": 50, "B": 50}
        total = 100
        # PMI = log2(0.05 / (0.5 * 0.5)) = log2(0.2) < 0
        results = pmi_edges(cooc, label_counts, total, threshold=2.0, min_count=3)
        assert len(results) == 0

    def test_empty_input(self):
        results = pmi_edges({}, {}, 0)
        assert results == []


# ============================================================================
# Frequency
# ============================================================================

class TestFrequencyEdges:

    def test_frequency_above_ratio_included(self):
        cooc = {("A", "B"): 10}
        results = frequency_edges(cooc, total_messages=100, min_count=3, min_ratio=0.05)
        assert len(results) == 1
        assert results[0][0] == "A"
        assert results[0][1] == "B"

    def test_frequency_below_ratio_excluded(self):
        cooc = {("A", "B"): 3}
        # ratio = 3/100 = 0.03 < 0.05
        results = frequency_edges(cooc, total_messages=100, min_count=3, min_ratio=0.05)
        assert len(results) == 0

    def test_min_count_enforced(self):
        cooc = {("A", "B"): 2}
        results = frequency_edges(cooc, total_messages=10, min_count=3, min_ratio=0.01)
        assert len(results) == 0

    def test_confidence_calculation(self):
        cooc = {("A", "B"): 10}
        results = frequency_edges(cooc, total_messages=100, min_count=3, min_ratio=0.05)
        # confidence = min(10 / (100 * 0.1), 1.0) = min(1.0, 1.0)
        assert results[0][2] == pytest.approx(1.0)

    def test_empty_messages(self):
        results = frequency_edges({}, total_messages=0)
        assert results == []


# ============================================================================
# Tiered Dispatch
# ============================================================================

class TestDiscoverEdges:

    def _make_graph(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["tech"]))
        g.add_node(Node(id="n2", label="Healthcare", tags=["domain"]))
        return g

    def test_small_dataset_uses_strict_threshold(self):
        g = self._make_graph()
        # < 100 messages with enough co-occurrences
        messages = ["Python Healthcare"] * 5
        edges = discover_edges(messages, g)
        # 5 co-occurrences, ratio = 5/5 = 1.0 > 0.05, count=5 >= 3
        assert len(edges) >= 1

    def test_small_dataset_filters_low_count(self):
        g = self._make_graph()
        # Only 2 co-occurrences (below min_count=3)
        messages = ["Python Healthcare", "Python Healthcare", "other stuff"]
        edges = discover_edges(messages, g)
        # count=2 < 3 → filtered out
        assert len(edges) == 0

    def test_existing_edges_not_duplicated(self):
        g = self._make_graph()
        g.add_edge(Edge(
            id="e1", source_id="n1", target_id="n2",
            relation="related", confidence=0.8,
        ))
        messages = ["Python Healthcare"] * 5
        edges = discover_edges(messages, g)
        assert len(edges) == 0

    def test_returns_edge_objects(self):
        g = self._make_graph()
        messages = ["Python Healthcare"] * 5
        edges = discover_edges(messages, g)
        if edges:
            e = edges[0]
            assert e.relation == "co_occurs"
            assert e.confidence <= 0.8
            assert e.properties.get("extraction") == "cooccurrence"

    def test_empty_labels_no_crash(self):
        g = CortexGraph()
        edges = discover_edges(["some message"], g)
        assert edges == []

    def test_empty_messages_no_crash(self):
        g = self._make_graph()
        edges = discover_edges([], g)
        assert edges == []


# ============================================================================
# Runner
# ============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
