"""Tests for diff_graphs() — Feature 2."""

import pytest
from cortex.graph import CortexGraph, Node, Edge, diff_graphs, make_node_id, make_edge_id


def _graph_with_nodes(*labels, tag="test"):
    g = CortexGraph()
    for label in labels:
        nid = make_node_id(label)
        g.add_node(Node(id=nid, label=label, tags=[tag], confidence=0.5))
    return g


class TestDiffGraphs:
    def test_identical_graphs(self):
        g = _graph_with_nodes("A", "B")
        d = diff_graphs(g, g)
        assert d["summary"]["added"] == 0
        assert d["summary"]["removed"] == 0
        assert d["summary"]["modified"] == 0

    def test_added_nodes(self):
        old = _graph_with_nodes("A")
        new = _graph_with_nodes("A", "B")
        d = diff_graphs(old, new)
        assert d["summary"]["added"] == 1
        assert d["added_nodes"][0]["label"] == "B"

    def test_removed_nodes(self):
        old = _graph_with_nodes("A", "B")
        new = _graph_with_nodes("A")
        d = diff_graphs(old, new)
        assert d["summary"]["removed"] == 1
        assert d["removed_nodes"][0]["label"] == "B"

    def test_modified_confidence(self):
        old = CortexGraph()
        nid = make_node_id("X")
        old.add_node(Node(id=nid, label="X", tags=["t"], confidence=0.3))
        new = CortexGraph()
        new.add_node(Node(id=nid, label="X", tags=["t"], confidence=0.9))
        d = diff_graphs(old, new)
        assert d["summary"]["modified"] == 1
        assert d["modified_nodes"][0]["changes"]["confidence"]["old"] == 0.3
        assert d["modified_nodes"][0]["changes"]["confidence"]["new"] == 0.9

    def test_modified_tags(self):
        old = CortexGraph()
        nid = make_node_id("Y")
        old.add_node(Node(id=nid, label="Y", tags=["a"]))
        new = CortexGraph()
        new.add_node(Node(id=nid, label="Y", tags=["a", "b"]))
        d = diff_graphs(old, new)
        assert d["summary"]["modified"] == 1
        assert "tags" in d["modified_nodes"][0]["changes"]

    def test_modified_label(self):
        nid = "fixed-id"
        old = CortexGraph()
        old.add_node(Node(id=nid, label="Old Label", tags=["t"]))
        new = CortexGraph()
        new.add_node(Node(id=nid, label="New Label", tags=["t"]))
        d = diff_graphs(old, new)
        assert d["summary"]["modified"] == 1
        assert d["modified_nodes"][0]["changes"]["label"]["old"] == "Old Label"

    def test_added_edges(self):
        old = CortexGraph()
        new = CortexGraph()
        a, b = make_node_id("A"), make_node_id("B")
        for g in (old, new):
            g.add_node(Node(id=a, label="A", tags=["t"]))
            g.add_node(Node(id=b, label="B", tags=["t"]))
        eid = make_edge_id(a, b, "knows")
        new.add_edge(Edge(id=eid, source_id=a, target_id=b, relation="knows"))
        d = diff_graphs(old, new)
        assert d["summary"]["edges_added"] == 1
        assert d["added_edges"][0]["relation"] == "knows"

    def test_removed_edges(self):
        old = CortexGraph()
        new = CortexGraph()
        a, b = make_node_id("A"), make_node_id("B")
        for g in (old, new):
            g.add_node(Node(id=a, label="A", tags=["t"]))
            g.add_node(Node(id=b, label="B", tags=["t"]))
        eid = make_edge_id(a, b, "knows")
        old.add_edge(Edge(id=eid, source_id=a, target_id=b, relation="knows"))
        d = diff_graphs(old, new)
        assert d["summary"]["edges_removed"] == 1

    def test_empty_to_full(self):
        old = CortexGraph()
        new = _graph_with_nodes("A", "B", "C")
        d = diff_graphs(old, new)
        assert d["summary"]["added"] == 3
        assert d["summary"]["removed"] == 0

    def test_full_to_empty(self):
        old = _graph_with_nodes("A", "B")
        new = CortexGraph()
        d = diff_graphs(old, new)
        assert d["summary"]["removed"] == 2
        assert d["summary"]["added"] == 0
