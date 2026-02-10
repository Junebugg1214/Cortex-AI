#!/usr/bin/env python3
"""
Tests for Cortex Phase 2: Contradiction Engine (v5.1)

Covers:
- Negation conflict: node in both positive and "negations" tag
- No false positives when no conflicts exist
- Temporal flip with >= 3 snapshots showing direction change >= 2 times
- Temporal flip returns empty with < 3 snapshots
- Source conflict: same label, different description hashes
- Tag conflict: node tags changed from positive to negation over snapshots
- Severity scoring correctness
- detect_all() aggregates all types, sorted by severity
- Filter by minimum severity
"""
from __future__ import annotations

import sys

from cortex.graph import CortexGraph, Node, make_node_id
from cortex.contradictions import ContradictionEngine, Contradiction


# ============================================================================
# Helpers
# ============================================================================

def _make_graph(*nodes: Node) -> CortexGraph:
    g = CortexGraph()
    for n in nodes:
        g.add_node(n)
    return g


def _make_node(label: str, tags: list[str] | None = None,
               confidence: float = 0.5, snapshots: list[dict] | None = None) -> Node:
    nid = make_node_id(label)
    return Node(
        id=nid, label=label,
        tags=tags or ["technical_expertise"],
        confidence=confidence,
        snapshots=snapshots or [],
    )


# ============================================================================
# Negation conflicts
# ============================================================================

class TestNegationConflicts:

    def test_detect_negation_conflict(self):
        """Node with both technical_expertise and negations = conflict."""
        node = _make_node("Python", tags=["technical_expertise", "negations"], confidence=0.8)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_negation_conflicts(g)
        assert len(results) == 1
        assert results[0].type == "negation_conflict"
        assert node.id in results[0].node_ids
        assert results[0].severity > 0.0

    def test_no_negation_conflict_when_clean(self):
        """Node with only positive tags = no conflict."""
        node = _make_node("Python", tags=["technical_expertise"])
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_negation_conflicts(g)
        assert len(results) == 0

    def test_no_negation_conflict_when_only_negations(self):
        """Node with only negations tag = no conflict (it's purely negative)."""
        node = _make_node("Hates Java", tags=["negations"])
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_negation_conflicts(g)
        assert len(results) == 0

    def test_negation_conflict_severity_scales_with_confidence(self):
        """Higher confidence node = higher severity."""
        node_low = _make_node("Python", tags=["technical_expertise", "negations"], confidence=0.1)
        node_high = _make_node("JavaScript", tags=["technical_expertise", "negations"], confidence=0.9)
        g = _make_graph(node_low, node_high)
        engine = ContradictionEngine()
        results = engine.detect_negation_conflicts(g)
        assert len(results) == 2
        severities = {r.node_ids[0]: r.severity for r in results}
        assert severities[node_high.id] > severities[node_low.id]


# ============================================================================
# Temporal flips
# ============================================================================

class TestTemporalFlips:

    def test_detect_temporal_flip(self):
        """Confidence flip-flopping across snapshots = temporal flip."""
        snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.3, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.8, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-03-01T00:00:00Z", "confidence": 0.4, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-04-01T00:00:00Z", "confidence": 0.9, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Python", snapshots=snapshots)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_temporal_flips(g)
        assert len(results) == 1
        assert results[0].type == "temporal_flip"

    def test_no_temporal_flip_with_insufficient_snapshots(self):
        """< 3 snapshots = no temporal flip detection."""
        snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.3, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.8, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Python", snapshots=snapshots)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_temporal_flips(g)
        assert len(results) == 0

    def test_no_temporal_flip_with_monotonic_confidence(self):
        """Steadily increasing confidence = no flip."""
        snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.3, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.5, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-03-01T00:00:00Z", "confidence": 0.8, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-04-01T00:00:00Z", "confidence": 0.9, "tags": ["technical_expertise"],
             "source": "extraction", "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Python", snapshots=snapshots)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_temporal_flips(g)
        assert len(results) == 0


# ============================================================================
# Source conflicts
# ============================================================================

class TestSourceConflicts:

    def test_detect_source_conflict(self):
        """Same label from different sources with different descriptions."""
        node_a = _make_node("Python")
        node_a.snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "source": "file_a",
             "confidence": 0.8, "tags": ["technical_expertise"],
             "properties_hash": "a", "description_hash": "hash_1"},
        ]
        # Create second node with same label but different ID (simulating collision-avoidance)
        node_b = Node(
            id=make_node_id("Python") + "x",  # different ID
            label="Python",
            tags=["technical_expertise"],
            confidence=0.7,
            snapshots=[
                {"timestamp": "2025-02-01T00:00:00Z", "source": "file_b",
                 "confidence": 0.7, "tags": ["technical_expertise"],
                 "properties_hash": "b", "description_hash": "hash_2"},
            ],
        )
        g = _make_graph(node_a, node_b)
        engine = ContradictionEngine()
        results = engine.detect_source_conflicts(g)
        assert len(results) == 1
        assert results[0].type == "source_conflict"

    def test_no_source_conflict_when_same_description(self):
        """Same label, same description hash = no conflict."""
        node_a = _make_node("Python")
        node_a.snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "source": "file_a",
             "confidence": 0.8, "tags": ["technical_expertise"],
             "properties_hash": "a", "description_hash": "same_hash"},
        ]
        node_b = Node(
            id=make_node_id("Python") + "x",
            label="Python",
            tags=["technical_expertise"],
            confidence=0.7,
            snapshots=[
                {"timestamp": "2025-02-01T00:00:00Z", "source": "file_b",
                 "confidence": 0.7, "tags": ["technical_expertise"],
                 "properties_hash": "b", "description_hash": "same_hash"},
            ],
        )
        g = _make_graph(node_a, node_b)
        engine = ContradictionEngine()
        results = engine.detect_source_conflicts(g)
        assert len(results) == 0


# ============================================================================
# Tag conflicts
# ============================================================================

class TestTagConflicts:

    def test_detect_tag_conflict_positive_to_negation(self):
        """Node moved from technical_expertise to negations."""
        snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "source": "extraction",
             "confidence": 0.8, "tags": ["technical_expertise"],
             "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-06-01T00:00:00Z", "source": "extraction",
             "confidence": 0.3, "tags": ["negations"],
             "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Java", snapshots=snapshots)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_tag_conflicts(g)
        assert len(results) == 1
        assert results[0].type == "tag_conflict"
        assert "technical_expertise" in results[0].description
        assert "negations" in results[0].description

    def test_detect_tag_conflict_negation_to_positive(self):
        """Node moved from negations to positive tag."""
        snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "source": "extraction",
             "confidence": 0.3, "tags": ["negations"],
             "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-06-01T00:00:00Z", "source": "extraction",
             "confidence": 0.8, "tags": ["values"],
             "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Work-life balance", snapshots=snapshots)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_tag_conflicts(g)
        assert len(results) == 1
        assert results[0].type == "tag_conflict"

    def test_no_tag_conflict_with_stable_tags(self):
        """Node stays in same tag family = no conflict."""
        snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "source": "extraction",
             "confidence": 0.5, "tags": ["technical_expertise"],
             "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-06-01T00:00:00Z", "source": "extraction",
             "confidence": 0.8, "tags": ["technical_expertise", "domain_knowledge"],
             "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Python", snapshots=snapshots)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_tag_conflicts(g)
        assert len(results) == 0

    def test_no_tag_conflict_with_single_snapshot(self):
        """< 2 snapshots = no tag conflict detection."""
        snapshots = [
            {"timestamp": "2025-01-01T00:00:00Z", "source": "extraction",
             "confidence": 0.5, "tags": ["technical_expertise"],
             "properties_hash": "a", "description_hash": "b"},
        ]
        node = _make_node("Python", snapshots=snapshots)
        g = _make_graph(node)
        engine = ContradictionEngine()
        results = engine.detect_tag_conflicts(g)
        assert len(results) == 0


# ============================================================================
# detect_all() aggregation
# ============================================================================

class TestDetectAll:

    def test_detect_all_aggregates_sorted_by_severity(self):
        """detect_all() combines all detectors and sorts by severity desc."""
        # Create a negation conflict (high severity)
        node_neg = _make_node("Python", tags=["technical_expertise", "negations"], confidence=0.9)
        # Create a tag conflict (medium severity)
        node_tag = _make_node("Java", snapshots=[
            {"timestamp": "2025-01-01T00:00:00Z", "source": "extraction",
             "confidence": 0.8, "tags": ["technical_expertise"],
             "properties_hash": "a", "description_hash": "b"},
            {"timestamp": "2025-06-01T00:00:00Z", "source": "extraction",
             "confidence": 0.3, "tags": ["negations"],
             "properties_hash": "a", "description_hash": "b"},
        ])
        g = _make_graph(node_neg, node_tag)
        engine = ContradictionEngine()
        results = engine.detect_all(g)
        assert len(results) >= 2
        # Sorted by severity desc
        for i in range(len(results) - 1):
            assert results[i].severity >= results[i + 1].severity

    def test_detect_all_with_min_severity_filter(self):
        """Filter contradictions by minimum severity."""
        node = _make_node("Python", tags=["technical_expertise", "negations"], confidence=0.9)
        g = _make_graph(node)
        engine = ContradictionEngine()

        all_results = engine.detect_all(g, min_severity=0.0)
        assert len(all_results) > 0

        # Very high severity filter should reduce results
        high_results = engine.detect_all(g, min_severity=0.99)
        assert len(high_results) <= len(all_results)

    def test_detect_all_empty_graph(self):
        """No contradictions in an empty graph."""
        g = CortexGraph()
        engine = ContradictionEngine()
        results = engine.detect_all(g)
        assert len(results) == 0

    def test_detect_all_clean_graph(self):
        """No contradictions in a well-formed graph."""
        g = _make_graph(
            _make_node("Python", tags=["technical_expertise"]),
            _make_node("Django", tags=["technical_expertise"]),
            _make_node("REST APIs", tags=["domain_knowledge"]),
        )
        engine = ContradictionEngine()
        results = engine.detect_all(g)
        assert len(results) == 0


# ============================================================================
# Run with pytest or standalone
# ============================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
