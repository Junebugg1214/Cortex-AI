#!/usr/bin/env python3
"""
Tests for Cortex Phase 2: Temporal Engine (v5.1)

Covers:
- Snapshot creation from node state
- create_snapshot() appends to all nodes
- Snapshot dict contains correct hashes
- graph_at() returns correct historical state
- Drift scoring with weighted Jaccard
- Drift "insufficient_data" with < 3 nodes
- Drift returns 0.0 for identical graphs
- Drift returns > 0 for different graphs
- Snapshot serialization roundtrip (to_dict/from_dict)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "skills" / "chatbot-memory-extractor" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "chatbot-memory-importer" / "scripts"))

from cortex.graph import CortexGraph, Node, Edge, make_node_id, make_edge_id
from cortex.temporal import (
    Snapshot, create_snapshot_dict, snapshot_from_dict,
    drift_score, _hash_dict, _hash_str, _weighted_jaccard,
    DRIFT_WEIGHTS,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_graph(*nodes: Node) -> CortexGraph:
    g = CortexGraph()
    for n in nodes:
        g.add_node(n)
    return g


def _make_node(label: str, tags: list[str] | None = None,
               confidence: float = 0.5, first_seen: str = "",
               last_seen: str = "", full_description: str = "",
               properties: dict | None = None) -> Node:
    nid = make_node_id(label)
    return Node(
        id=nid, label=label,
        tags=tags or ["technical_expertise"],
        confidence=confidence,
        first_seen=first_seen,
        last_seen=last_seen,
        full_description=full_description,
        properties=properties or {},
    )


# ============================================================================
# Snapshot creation
# ============================================================================

class TestSnapshotCreation:

    def test_create_snapshot_dict_basic(self):
        node = _make_node("Python", confidence=0.9, full_description="A language")
        snap = create_snapshot_dict(node, "extraction", timestamp="2025-01-15T00:00:00Z")
        assert snap["timestamp"] == "2025-01-15T00:00:00Z"
        assert snap["source"] == "extraction"
        assert snap["confidence"] == 0.9
        assert snap["tags"] == ["technical_expertise"]
        assert isinstance(snap["properties_hash"], str)
        assert isinstance(snap["description_hash"], str)
        assert len(snap["properties_hash"]) == 16
        assert len(snap["description_hash"]) == 16

    def test_create_snapshot_dict_auto_timestamp(self):
        node = _make_node("JavaScript")
        snap = create_snapshot_dict(node, "manual")
        assert snap["timestamp"]  # non-empty
        assert "T" in snap["timestamp"]  # ISO-8601 format

    def test_snapshot_hashes_differ_for_different_content(self):
        node_a = _make_node("Python", full_description="A language")
        node_b = _make_node("Python", full_description="A different language")
        snap_a = create_snapshot_dict(node_a, "extraction", timestamp="2025-01-15T00:00:00Z")
        snap_b = create_snapshot_dict(node_b, "extraction", timestamp="2025-01-15T00:00:00Z")
        assert snap_a["description_hash"] != snap_b["description_hash"]

    def test_snapshot_hashes_same_for_same_content(self):
        node_a = _make_node("Python", full_description="A language")
        node_b = _make_node("Python", full_description="A language")
        snap_a = create_snapshot_dict(node_a, "extraction", timestamp="2025-01-15T00:00:00Z")
        snap_b = create_snapshot_dict(node_b, "extraction", timestamp="2025-01-15T00:00:00Z")
        assert snap_a["description_hash"] == snap_b["description_hash"]

    def test_snapshot_from_dict_roundtrip(self):
        node = _make_node("Python", confidence=0.85, full_description="A language",
                          properties={"version": "3.11"})
        snap_dict = create_snapshot_dict(node, "merge", timestamp="2025-02-01T12:00:00Z")
        snap = snapshot_from_dict(snap_dict)
        assert snap.timestamp == "2025-02-01T12:00:00Z"
        assert snap.source == "merge"
        assert snap.confidence == 0.85
        assert snap.tags == ["technical_expertise"]
        assert snap.properties_hash == snap_dict["properties_hash"]
        assert snap.description_hash == snap_dict["description_hash"]


# ============================================================================
# CortexGraph.create_snapshot()
# ============================================================================

class TestGraphCreateSnapshot:

    def test_create_snapshot_appends_to_all_nodes(self):
        g = _make_graph(
            _make_node("Python"),
            _make_node("JavaScript"),
            _make_node("Rust"),
        )
        g.create_snapshot("extraction", timestamp="2025-01-15T00:00:00Z")
        for node in g.nodes.values():
            assert len(node.snapshots) == 1
            assert node.snapshots[0]["source"] == "extraction"

    def test_create_snapshot_multiple_calls(self):
        g = _make_graph(_make_node("Python"))
        g.create_snapshot("extraction", timestamp="2025-01-15T00:00:00Z")
        g.create_snapshot("merge", timestamp="2025-02-01T00:00:00Z")
        node = list(g.nodes.values())[0]
        assert len(node.snapshots) == 2
        assert node.snapshots[0]["source"] == "extraction"
        assert node.snapshots[1]["source"] == "merge"

    def test_create_snapshot_preserves_node_state(self):
        node = _make_node("Python", confidence=0.9)
        g = _make_graph(node)
        g.create_snapshot("extraction", timestamp="2025-01-15T00:00:00Z")
        snap = node.snapshots[0]
        assert snap["confidence"] == 0.9
        assert snap["tags"] == ["technical_expertise"]


# ============================================================================
# CortexGraph.graph_at()
# ============================================================================

class TestGraphAt:

    def test_graph_at_returns_correct_snapshot_state(self):
        node = _make_node("Python", confidence=0.5, first_seen="2025-01-01T00:00:00Z")
        g = _make_graph(node)
        node.snapshots.append({
            "timestamp": "2025-01-15T00:00:00Z",
            "source": "extraction",
            "confidence": 0.7,
            "tags": ["technical_expertise"],
            "properties_hash": "abc",
            "description_hash": "def",
        })
        node.snapshots.append({
            "timestamp": "2025-02-15T00:00:00Z",
            "source": "merge",
            "confidence": 0.9,
            "tags": ["technical_expertise", "domain_knowledge"],
            "properties_hash": "ghi",
            "description_hash": "jkl",
        })

        # At Jan 20 — should use Jan 15 snapshot
        historical = g.graph_at("2025-01-20T00:00:00Z")
        h_node = list(historical.nodes.values())[0]
        assert h_node.confidence == 0.7
        assert h_node.tags == ["technical_expertise"]
        assert len(h_node.snapshots) == 1

    def test_graph_at_excludes_future_nodes(self):
        node_a = _make_node("Python", first_seen="2025-01-01T00:00:00Z")
        node_b = _make_node("Rust", first_seen="2025-03-01T00:00:00Z")
        g = _make_graph(node_a, node_b)

        historical = g.graph_at("2025-02-01T00:00:00Z")
        assert len(historical.nodes) == 1
        assert list(historical.nodes.values())[0].label == "Python"

    def test_graph_at_includes_nodes_without_first_seen(self):
        node = _make_node("Python")  # no first_seen
        g = _make_graph(node)
        historical = g.graph_at("2025-01-01T00:00:00Z")
        assert len(historical.nodes) == 1

    def test_graph_at_preserves_edges_for_included_nodes(self):
        node_a = _make_node("Python", first_seen="2025-01-01T00:00:00Z")
        node_b = _make_node("Django", first_seen="2025-01-01T00:00:00Z")
        g = _make_graph(node_a, node_b)
        eid = make_edge_id(node_a.id, node_b.id, "uses")
        g.add_edge(Edge(id=eid, source_id=node_a.id, target_id=node_b.id, relation="uses"))

        historical = g.graph_at("2025-02-01T00:00:00Z")
        assert len(historical.edges) == 1

    def test_graph_at_drops_edges_for_excluded_nodes(self):
        node_a = _make_node("Python", first_seen="2025-01-01T00:00:00Z")
        node_b = _make_node("Rust", first_seen="2025-06-01T00:00:00Z")
        g = _make_graph(node_a, node_b)
        eid = make_edge_id(node_a.id, node_b.id, "related_to")
        g.add_edge(Edge(id=eid, source_id=node_a.id, target_id=node_b.id, relation="related_to"))

        historical = g.graph_at("2025-02-01T00:00:00Z")
        assert len(historical.edges) == 0


# ============================================================================
# Snapshot serialization roundtrip
# ============================================================================

class TestSnapshotSerialization:

    def test_node_to_dict_includes_snapshots(self):
        node = _make_node("Python")
        node.snapshots.append({
            "timestamp": "2025-01-15T00:00:00Z",
            "source": "extraction",
            "confidence": 0.8,
            "tags": ["technical_expertise"],
            "properties_hash": "abc",
            "description_hash": "def",
        })
        d = node.to_dict()
        assert "snapshots" in d
        assert len(d["snapshots"]) == 1
        assert d["snapshots"][0]["source"] == "extraction"

    def test_node_from_dict_loads_snapshots(self):
        d = {
            "id": "abc123",
            "label": "Python",
            "tags": ["technical_expertise"],
            "snapshots": [{
                "timestamp": "2025-01-15T00:00:00Z",
                "source": "extraction",
                "confidence": 0.8,
                "tags": ["technical_expertise"],
                "properties_hash": "abc",
                "description_hash": "def",
            }],
        }
        node = Node.from_dict(d)
        assert len(node.snapshots) == 1
        assert node.snapshots[0]["source"] == "extraction"

    def test_node_from_dict_defaults_empty_snapshots(self):
        """v5.0 data without snapshots field loads with empty list."""
        d = {"id": "abc123", "label": "Python", "tags": ["technical_expertise"]}
        node = Node.from_dict(d)
        assert node.snapshots == []

    def test_v5_json_roundtrip_with_snapshots(self):
        g = _make_graph(_make_node("Python"))
        g.create_snapshot("extraction", timestamp="2025-01-15T00:00:00Z")
        exported = g.export_v5()
        loaded = CortexGraph.from_v5_json(exported)
        node = list(loaded.nodes.values())[0]
        assert len(node.snapshots) == 1
        assert node.snapshots[0]["source"] == "extraction"


# ============================================================================
# Drift scoring
# ============================================================================

class TestDriftScoring:

    def test_drift_identical_graphs(self):
        g = _make_graph(
            _make_node("Python", tags=["technical_expertise"]),
            _make_node("Django", tags=["technical_expertise"]),
            _make_node("REST APIs", tags=["domain_knowledge"]),
        )
        result = drift_score(g, g)
        assert result["sufficient_data"] is True
        assert result["score"] == 0.0

    def test_drift_completely_different_graphs(self):
        g_a = _make_graph(
            _make_node("Python", tags=["technical_expertise"]),
            _make_node("Django", tags=["technical_expertise"]),
            _make_node("REST APIs", tags=["domain_knowledge"]),
        )
        g_b = _make_graph(
            _make_node("Rust", tags=["technical_expertise"]),
            _make_node("Tokio", tags=["technical_expertise"]),
            _make_node("Systems Programming", tags=["domain_knowledge"]),
        )
        result = drift_score(g_a, g_b)
        assert result["sufficient_data"] is True
        assert result["score"] > 0.0

    def test_drift_insufficient_data_small_graph(self):
        g_a = _make_graph(_make_node("Python"))
        g_b = _make_graph(
            _make_node("Python"),
            _make_node("Django"),
            _make_node("REST APIs"),
        )
        result = drift_score(g_a, g_b)
        assert result["sufficient_data"] is False
        assert result["score"] == 0.0

    def test_drift_insufficient_data_both_small(self):
        g_a = _make_graph(_make_node("Python"), _make_node("Django"))
        g_b = _make_graph(_make_node("Rust"), _make_node("Tokio"))
        result = drift_score(g_a, g_b)
        assert result["sufficient_data"] is False

    def test_drift_partial_overlap(self):
        g_a = _make_graph(
            _make_node("Python", tags=["technical_expertise"], confidence=0.9),
            _make_node("Django", tags=["technical_expertise"]),
            _make_node("REST APIs", tags=["domain_knowledge"]),
        )
        g_b = _make_graph(
            _make_node("Python", tags=["technical_expertise"], confidence=0.5),
            _make_node("Rust", tags=["technical_expertise"]),
            _make_node("REST APIs", tags=["domain_knowledge"]),
        )
        result = drift_score(g_a, g_b)
        assert result["sufficient_data"] is True
        assert 0.0 < result["score"] < 1.0
        assert result["details"]["confidence_drift"] > 0.0


# ============================================================================
# Weighted Jaccard
# ============================================================================

class TestWeightedJaccard:

    def test_identical_sets(self):
        assert _weighted_jaccard({"a", "b"}, {"a", "b"}, {}) == 0.0

    def test_disjoint_sets(self):
        assert _weighted_jaccard({"a"}, {"b"}, {}) == 1.0

    def test_empty_sets(self):
        assert _weighted_jaccard(set(), set(), {}) == 0.0

    def test_weighted_overlap(self):
        weights = {"identity": 3.0, "values": 2.0}
        # {identity, values} vs {identity, technical}
        # intersection = {identity} weight=3, union = {identity, values, technical} weight=3+2+1=6
        result = _weighted_jaccard({"identity", "values"}, {"identity", "technical"}, weights)
        assert abs(result - (1.0 - 3.0 / 6.0)) < 0.001


# ============================================================================
# Hash helpers
# ============================================================================

class TestHashHelpers:

    def test_hash_dict_deterministic(self):
        d = {"b": 2, "a": 1}
        assert _hash_dict(d) == _hash_dict({"a": 1, "b": 2})

    def test_hash_str_deterministic(self):
        assert _hash_str("hello") == _hash_str("hello")
        assert _hash_str("hello") != _hash_str("world")


# ============================================================================
# Run with pytest or standalone
# ============================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
