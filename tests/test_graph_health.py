"""Tests for CortexGraph.graph_health() — Feature 1."""

from datetime import datetime, timedelta, timezone

from cortex.graph.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id


def _make_graph(**kwargs):
    return CortexGraph(**kwargs)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


class TestGraphHealth:
    def test_empty_graph(self):
        g = _make_graph()
        h = g.graph_health()
        assert h["total_nodes"] == 0
        assert h["total_edges"] == 0
        assert h["stale_count"] == 0
        assert h["orphan_count"] == 0
        assert h["avg_confidence"] == 0.0
        assert h["confidence_distribution"]["0.0-0.2"] == 0

    def test_stale_nodes_detected(self):
        g = _make_graph()
        nid = make_node_id("old-node")
        g.add_node(Node(id=nid, label="Old Node", tags=["test"], confidence=0.8, last_seen=_days_ago(60)))
        fresh_id = make_node_id("fresh-node")
        g.add_node(Node(id=fresh_id, label="Fresh Node", tags=["test"], confidence=0.9, last_seen=_now_iso()))
        h = g.graph_health(stale_days=30)
        assert h["stale_count"] == 1
        assert h["stale_nodes"][0]["id"] == nid
        assert h["stale_nodes"][0]["days_stale"] >= 59

    def test_stale_falls_back_to_first_seen(self):
        g = _make_graph()
        nid = make_node_id("old2")
        g.add_node(Node(id=nid, label="Old2", tags=["t"], confidence=0.5, first_seen=_days_ago(45)))
        h = g.graph_health(stale_days=30)
        assert h["stale_count"] == 1

    def test_nodes_without_dates_not_stale(self):
        g = _make_graph()
        nid = make_node_id("no-date")
        g.add_node(Node(id=nid, label="No Date", tags=["t"]))
        h = g.graph_health()
        assert h["stale_count"] == 0

    def test_custom_stale_days(self):
        g = _make_graph()
        nid = make_node_id("border")
        g.add_node(Node(id=nid, label="Border", tags=["t"], last_seen=_days_ago(10)))
        assert g.graph_health(stale_days=5)["stale_count"] == 1
        assert g.graph_health(stale_days=15)["stale_count"] == 0

    def test_orphan_nodes_detected(self):
        g = _make_graph()
        orphan_id = make_node_id("orphan")
        connected_a = make_node_id("connected-a")
        connected_b = make_node_id("connected-b")
        g.add_node(Node(id=orphan_id, label="Orphan", tags=["t"]))
        g.add_node(Node(id=connected_a, label="A", tags=["t"]))
        g.add_node(Node(id=connected_b, label="B", tags=["t"]))
        eid = make_edge_id(connected_a, connected_b, "related")
        g.add_edge(Edge(id=eid, source_id=connected_a, target_id=connected_b, relation="related"))

        h = g.graph_health()
        assert h["orphan_count"] == 1
        assert h["orphan_nodes"][0]["id"] == orphan_id

    def test_confidence_distribution(self):
        g = _make_graph()
        confs = [0.1, 0.3, 0.5, 0.7, 0.9]
        for i, c in enumerate(confs):
            nid = make_node_id(f"node-{i}")
            g.add_node(Node(id=nid, label=f"Node {i}", tags=["t"], confidence=c))

        h = g.graph_health()
        dist = h["confidence_distribution"]
        assert dist["0.0-0.2"] == 1
        assert dist["0.2-0.4"] == 1
        assert dist["0.4-0.6"] == 1
        assert dist["0.6-0.8"] == 1
        assert dist["0.8-1.0"] == 1

    def test_avg_confidence(self):
        g = _make_graph()
        for i in range(4):
            nid = make_node_id(f"avg-{i}")
            g.add_node(Node(id=nid, label=f"Avg {i}", tags=["t"], confidence=0.8))
        h = g.graph_health()
        assert h["avg_confidence"] == 0.8

    def test_avg_confidence_per_tag(self):
        g = _make_graph()
        n1 = make_node_id("skill-a")
        n2 = make_node_id("skill-b")
        n3 = make_node_id("identity-a")
        g.add_node(Node(id=n1, label="Skill A", tags=["skills"], confidence=0.6))
        g.add_node(Node(id=n2, label="Skill B", tags=["skills"], confidence=0.8))
        g.add_node(Node(id=n3, label="Identity A", tags=["identity"], confidence=1.0))

        h = g.graph_health()
        assert h["avg_confidence_per_tag"]["skills"] == 0.7
        assert h["avg_confidence_per_tag"]["identity"] == 1.0

    def test_totals(self):
        g = _make_graph()
        a = make_node_id("a")
        b = make_node_id("b")
        g.add_node(Node(id=a, label="A", tags=["t"]))
        g.add_node(Node(id=b, label="B", tags=["t"]))
        eid = make_edge_id(a, b, "r")
        g.add_edge(Edge(id=eid, source_id=a, target_id=b, relation="r"))
        h = g.graph_health()
        assert h["total_nodes"] == 2
        assert h["total_edges"] == 1
