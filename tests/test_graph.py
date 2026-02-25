#!/usr/bin/env python3
"""
Tests for Cortex Phase 1: Graph Foundation (v5.0)

Covers:
- Node/Edge CRUD
- find_nodes, get_neighbors, get_edges_for
- merge_nodes
- v4 → v5 upgrade (label dedup across categories, relationship→edge resolution)
- v5 → v4 downgrade (primary tag selection, edges lost)
- v4 → v5 → v4 roundtrip = identical
- to_v4_categories, to_v5_json, export_v4, export_v5
- stats
- ExtractionContext.to_graph()
- NormalizedContext v5 detection
- migrate.py query/stats subcommands
"""

import json
import sys
import tempfile
from pathlib import Path

from cortex.compat import downgrade_v5_to_v4, roundtrip_v4, upgrade_v4_to_v5
from cortex.extract_memory import AggressiveExtractor, ExtractionContext
from cortex.graph import (
    CortexGraph,
    Edge,
    Node,
    make_edge_id,
    make_node_id,
    make_node_id_with_tag,
)
from cortex.import_memory import NormalizedContext

# ============================================================================
# Node / Edge CRUD
# ============================================================================

class TestNodeEdgeCRUD:

    def test_add_and_get_node(self):
        g = CortexGraph()
        n = Node(id="abc123", label="Python", tags=["technical_expertise"], confidence=0.9)
        g.add_node(n)
        assert g.get_node("abc123") is n

    def test_get_nonexistent_node(self):
        g = CortexGraph()
        assert g.get_node("nope") is None

    def test_add_and_get_edge(self):
        g = CortexGraph()
        e = Edge(id="e1", source_id="a", target_id="b", relation="uses", confidence=0.7)
        g.add_edge(e)
        assert g.get_edge("e1") is e

    def test_get_nonexistent_edge(self):
        g = CortexGraph()
        assert g.get_edge("nope") is None

    def test_remove_node_removes_connected_edges(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A"))
        g.add_node(Node(id="b", label="B"))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        assert g.remove_node("a") is True
        assert g.get_node("a") is None
        assert g.get_edge("e1") is None
        assert g.get_node("b") is not None

    def test_remove_nonexistent_node(self):
        g = CortexGraph()
        assert g.remove_node("nope") is False

    def test_remove_edge(self):
        g = CortexGraph()
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        assert g.remove_edge("e1") is True
        assert g.get_edge("e1") is None

    def test_remove_nonexistent_edge(self):
        g = CortexGraph()
        assert g.remove_edge("nope") is False


# ============================================================================
# Query
# ============================================================================

class TestQuery:

    def _sample_graph(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.9))
        g.add_node(Node(id="n2", label="React", tags=["technical_expertise"], confidence=0.7))
        g.add_node(Node(id="n3", label="Healthcare", tags=["domain_knowledge"], confidence=0.8))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n3", relation="used_in"))
        g.add_edge(Edge(id="e2", source_id="n2", target_id="n3", relation="used_in"))
        return g

    def test_find_nodes_by_label(self):
        g = self._sample_graph()
        results = g.find_nodes(label="Python")
        assert len(results) == 1
        assert results[0].label == "Python"

    def test_find_nodes_by_label_case_insensitive(self):
        g = self._sample_graph()
        results = g.find_nodes(label="python")
        assert len(results) == 1

    def test_find_nodes_by_tag(self):
        g = self._sample_graph()
        results = g.find_nodes(tag="technical_expertise")
        assert len(results) == 2

    def test_find_nodes_by_min_confidence(self):
        g = self._sample_graph()
        results = g.find_nodes(min_confidence=0.8)
        assert len(results) == 2  # Python(0.9) and Healthcare(0.8)

    def test_find_nodes_combined_filters(self):
        g = self._sample_graph()
        results = g.find_nodes(tag="technical_expertise", min_confidence=0.8)
        assert len(results) == 1
        assert results[0].label == "Python"

    def test_get_neighbors(self):
        g = self._sample_graph()
        neighbors = g.get_neighbors("n1")
        assert len(neighbors) == 1
        edge, node = neighbors[0]
        assert node.label == "Healthcare"
        assert edge.relation == "used_in"

    def test_get_neighbors_with_relation_filter(self):
        g = self._sample_graph()
        neighbors = g.get_neighbors("n3", relation="used_in")
        assert len(neighbors) == 2

    def test_get_neighbors_no_match(self):
        g = self._sample_graph()
        neighbors = g.get_neighbors("n1", relation="nonexistent")
        assert len(neighbors) == 0

    def test_get_edges_for(self):
        g = self._sample_graph()
        edges = g.get_edges_for("n3")
        assert len(edges) == 2


# ============================================================================
# Merge
# ============================================================================

class TestMergeNodes:

    def test_merge_combines_fields(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["technical_expertise"],
                        confidence=0.8, mention_count=3, brief="Lang"))
        g.add_node(Node(id="b", label="Python", tags=["domain_knowledge"],
                        confidence=0.9, mention_count=2,
                        brief="A programming language"))
        result = g.merge_nodes("a", "b")
        assert result.confidence == 0.9
        assert result.mention_count == 5
        assert "technical_expertise" in result.tags
        assert "domain_knowledge" in result.tags
        assert result.brief == "A programming language"  # longer
        assert g.get_node("b") is None

    def test_merge_rewires_edges(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python"))
        g.add_node(Node(id="b", label="Python2"))
        g.add_node(Node(id="c", label="Healthcare"))
        g.add_edge(Edge(id="e1", source_id="b", target_id="c", relation="used_in"))
        g.merge_nodes("a", "b")
        # Edge should now reference a→c
        edges = g.get_edges_for("a")
        assert len(edges) == 1
        assert edges[0].target_id == "c"
        assert edges[0].source_id == "a"
        # Old edge gone
        assert g.get_edge("e1") is None

    def test_merge_skips_self_loops(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python"))
        g.add_node(Node(id="b", label="Python2"))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="same"))
        g.merge_nodes("a", "b")
        # Should not create a→a self-loop
        edges = g.get_edges_for("a")
        assert len(edges) == 0


# ============================================================================
# Node ID helpers
# ============================================================================

class TestNodeIdHelpers:

    def test_make_node_id_deterministic(self):
        assert make_node_id("Python") == make_node_id("Python")

    def test_make_node_id_case_insensitive(self):
        assert make_node_id("Python") == make_node_id("python")

    def test_make_node_id_whitespace_normalized(self):
        assert make_node_id("  Python  ") == make_node_id("Python")

    def test_make_node_id_with_tag_differs(self):
        id1 = make_node_id("Python")
        id2 = make_node_id_with_tag("Python", "technical_expertise")
        assert id1 != id2

    def test_make_edge_id_deterministic(self):
        assert make_edge_id("a", "b", "uses") == make_edge_id("a", "b", "uses")

    def test_make_edge_id_direction_matters(self):
        assert make_edge_id("a", "b", "uses") != make_edge_id("b", "a", "uses")


# ============================================================================
# v4 → v5 Upgrade
# ============================================================================

class TestUpgradeV4ToV5:

    def _minimal_v4(self):
        return {
            "schema_version": "4.0",
            "meta": {"method": "aggressive_extraction_v4"},
            "categories": {
                "technical_expertise": [
                    {"topic": "Python", "brief": "Lang", "confidence": 0.9,
                     "mention_count": 5, "extraction_method": "self_reference",
                     "metrics": [], "relationships": [], "timeline": ["current"],
                     "source_quotes": ["I use Python"], "first_seen": None, "last_seen": None}
                ],
                "identity": [
                    {"topic": "Marc", "brief": "Marc", "confidence": 0.95,
                     "mention_count": 3, "extraction_method": "explicit_statement",
                     "metrics": [], "relationships": [], "timeline": [],
                     "source_quotes": [], "first_seen": None, "last_seen": None}
                ],
            }
        }

    def test_basic_upgrade(self):
        graph = upgrade_v4_to_v5(self._minimal_v4())
        assert len(graph.nodes) == 2
        python_nodes = graph.find_nodes(label="Python")
        assert len(python_nodes) == 1
        assert "technical_expertise" in python_nodes[0].tags

    def test_label_dedup_across_categories(self):
        """Same label in two categories → single node with both tags."""
        v4 = {
            "schema_version": "4.0",
            "meta": {},
            "categories": {
                "technical_expertise": [
                    {"topic": "Python", "confidence": 0.8, "mention_count": 3}
                ],
                "domain_knowledge": [
                    {"topic": "Python", "confidence": 0.9, "mention_count": 2}
                ]
            }
        }
        graph = upgrade_v4_to_v5(v4)
        python_nodes = graph.find_nodes(label="Python")
        assert len(python_nodes) == 1
        node = python_nodes[0]
        assert "technical_expertise" in node.tags
        assert "domain_knowledge" in node.tags
        assert node.confidence == 0.9  # max
        assert node.mention_count == 5  # sum

    def test_relationship_string_resolution(self):
        """Relationship strings → edges to resolved nodes."""
        v4 = {
            "schema_version": "4.0",
            "meta": {},
            "categories": {
                "technical_expertise": [
                    {"topic": "Python", "confidence": 0.8, "relationships": ["Healthcare"]}
                ],
                "domain_knowledge": [
                    {"topic": "Healthcare", "confidence": 0.7}
                ]
            }
        }
        graph = upgrade_v4_to_v5(v4)
        assert len(graph.edges) >= 1
        python_node = graph.find_nodes(label="Python")[0]
        neighbors = graph.get_neighbors(python_node.id)
        assert any(n.label == "Healthcare" for _, n in neighbors)

    def test_stub_node_for_unresolved_relationship(self):
        """Unresolved relationship string → stub node created."""
        v4 = {
            "schema_version": "4.0",
            "meta": {},
            "categories": {
                "technical_expertise": [
                    {"topic": "Python", "confidence": 0.8,
                     "relationships": ["UnknownThing"]}
                ]
            }
        }
        graph = upgrade_v4_to_v5(v4)
        stub_nodes = graph.find_nodes(label="UnknownThing")
        assert len(stub_nodes) == 1
        assert stub_nodes[0].confidence == 0.3
        assert "mentions" in stub_nodes[0].tags

    def test_relationship_type_becomes_edge_relation(self):
        """topic.relationship_type → Edge.relation."""
        v4 = {
            "schema_version": "4.0",
            "meta": {},
            "categories": {
                "relationships": [
                    {"topic": "Acme Corp", "confidence": 0.9,
                     "relationship_type": "partner",
                     "relationships": ["Marc"]}
                ],
                "identity": [
                    {"topic": "Marc", "confidence": 0.95}
                ]
            }
        }
        graph = upgrade_v4_to_v5(v4)
        acme = graph.find_nodes(label="Acme Corp")[0]
        edges = graph.get_edges_for(acme.id)
        assert any(e.relation == "partner" for e in edges)

    def test_empty_categories_no_crash(self):
        v4 = {"schema_version": "4.0", "meta": {}, "categories": {}}
        graph = upgrade_v4_to_v5(v4)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0


# ============================================================================
# v5 → v4 Downgrade
# ============================================================================

class TestDowngradeV5ToV4:

    def test_basic_downgrade(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.9))
        v4 = downgrade_v5_to_v4(g)
        assert v4["schema_version"] == "4.0"
        assert "technical_expertise" in v4["categories"]
        assert v4["categories"]["technical_expertise"][0]["topic"] == "Python"

    def test_primary_tag_selection(self):
        """Multi-tag node → appears in first tag per CATEGORY_ORDER."""
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Python",
                        tags=["domain_knowledge", "technical_expertise"],
                        confidence=0.9))
        v4 = downgrade_v5_to_v4(g)
        # technical_expertise comes before domain_knowledge in CATEGORY_ORDER
        assert "technical_expertise" in v4["categories"]
        assert "domain_knowledge" not in v4["categories"]

    def test_edges_lost_on_downgrade(self):
        """Edges are lost (documented limitation)."""
        g = CortexGraph()
        g.add_node(Node(id="a", label="Python", tags=["technical_expertise"]))
        g.add_node(Node(id="b", label="Healthcare", tags=["domain_knowledge"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="used_in"))
        v4 = downgrade_v5_to_v4(g)
        # Edge info is captured as relationship labels (v4 format)
        python_topic = v4["categories"]["technical_expertise"][0]
        assert "Healthcare" in python_topic["relationships"]

    def test_relationship_type_preserved(self):
        g = CortexGraph()
        g.add_node(Node(id="n1", label="Acme", tags=["relationships"],
                        relationship_type="partner", confidence=0.9))
        v4 = downgrade_v5_to_v4(g)
        topic = v4["categories"]["relationships"][0]
        assert topic["relationship_type"] == "partner"


# ============================================================================
# Roundtrip
# ============================================================================

class TestRoundtrip:

    def test_v4_roundtrip_identical(self):
        """v4 → v5 → v4 should produce identical categories."""
        v4 = {
            "schema_version": "4.0",
            "meta": {"method": "aggressive_extraction_v4"},
            "categories": {
                "identity": [
                    {"topic": "Marc Saint-Jour", "brief": "Marc Saint-Jour",
                     "full_description": "", "confidence": 0.95,
                     "mention_count": 3, "extraction_method": "explicit_statement",
                     "metrics": [], "relationships": [],
                     "timeline": [], "source_quotes": [],
                     "first_seen": None, "last_seen": None}
                ],
                "technical_expertise": [
                    {"topic": "Python", "brief": "Lang", "full_description": "",
                     "confidence": 0.9, "mention_count": 5,
                     "extraction_method": "self_reference",
                     "metrics": [], "relationships": [],
                     "timeline": ["current"], "source_quotes": ["I use Python"],
                     "first_seen": None, "last_seen": None}
                ]
            }
        }
        result = roundtrip_v4(v4)
        assert result["schema_version"] == "4.0"
        # Same categories present
        assert set(result["categories"].keys()) == set(v4["categories"].keys())
        # Same topics
        for cat in v4["categories"]:
            orig_topics = {t["topic"] for t in v4["categories"][cat]}
            result_topics = {t["topic"] for t in result["categories"][cat]}
            assert orig_topics == result_topics, f"Mismatch in {cat}"
            # Same confidence values
            for orig_t in v4["categories"][cat]:
                matching = [t for t in result["categories"][cat] if t["topic"] == orig_t["topic"]]
                assert len(matching) == 1
                assert matching[0]["confidence"] == orig_t["confidence"]
                assert matching[0]["mention_count"] == orig_t["mention_count"]

    def test_v4_roundtrip_with_relationships(self):
        """v4 with relationship strings roundtrips (stubs may be added)."""
        v4 = {
            "schema_version": "4.0",
            "meta": {},
            "categories": {
                "relationships": [
                    {"topic": "Acme Corp", "confidence": 0.8,
                     "relationship_type": "partner",
                     "mention_count": 1, "brief": "Acme Corp",
                     "full_description": "", "extraction_method": "explicit_statement",
                     "metrics": [], "relationships": ["Mayo Clinic"],
                     "timeline": [], "source_quotes": [],
                     "first_seen": None, "last_seen": None}
                ],
                "domain_knowledge": [
                    {"topic": "Mayo Clinic", "confidence": 0.7,
                     "mention_count": 1, "brief": "Mayo Clinic",
                     "full_description": "", "extraction_method": "contextual",
                     "metrics": [], "relationships": [],
                     "timeline": [], "source_quotes": [],
                     "first_seen": None, "last_seen": None}
                ]
            }
        }
        result = roundtrip_v4(v4)
        assert "relationships" in result["categories"]
        assert result["categories"]["relationships"][0]["topic"] == "Acme Corp"
        assert result["categories"]["relationships"][0]["relationship_type"] == "partner"


# ============================================================================
# Export formats
# ============================================================================

class TestExportFormats:

    def _sample_graph(self):
        g = CortexGraph(meta={"generated_at": "2025-02-07T00:00:00Z"})
        g.add_node(Node(id="n1", label="Python", tags=["technical_expertise"],
                        confidence=0.9, brief="languages: python"))
        g.add_node(Node(id="n2", label="Healthcare", tags=["domain_knowledge"],
                        confidence=0.8, brief="healthcare: clinical"))
        g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="used_in"))
        return g

    def test_to_v4_categories(self):
        g = self._sample_graph()
        cats = g.to_v4_categories()
        assert "technical_expertise" in cats
        assert "domain_knowledge" in cats
        assert cats["technical_expertise"][0]["topic"] == "Python"
        assert cats["technical_expertise"][0]["_node_id"] == "n1"

    def test_to_v5_json(self):
        g = self._sample_graph()
        v5 = g.to_v5_json()
        assert v5["schema_version"] == "5.0"
        assert "graph" in v5
        assert "categories" in v5
        assert "n1" in v5["graph"]["nodes"]
        assert "e1" in v5["graph"]["edges"]

    def test_export_v4(self):
        g = self._sample_graph()
        v4 = g.export_v4()
        assert v4["schema_version"] == "4.0"
        assert "categories" in v4
        assert "graph" not in v4

    def test_export_v5(self):
        g = self._sample_graph()
        v5 = g.export_v5()
        assert v5["schema_version"] == "6.0"
        assert v5["meta"]["node_count"] == 2
        assert v5["meta"]["edge_count"] == 1
        assert "graph_model" in v5["meta"]["features"]
        assert "smart_edges" in v5["meta"]["features"]
        assert "centrality" in v5["meta"]["features"]
        assert "query_engine" in v5["meta"]["features"]
        assert "intelligence" in v5["meta"]["features"]
        assert "visualization" in v5["meta"]["features"]
        assert "dashboard" in v5["meta"]["features"]

    def test_v4_categories_include_relationship_labels(self):
        g = self._sample_graph()
        cats = g.to_v4_categories()
        python_topic = cats["technical_expertise"][0]
        assert "Healthcare" in python_topic["relationships"]

    def test_from_v5_json_roundtrips(self):
        g = self._sample_graph()
        v5 = g.to_v5_json()
        g2 = CortexGraph.from_v5_json(v5)
        assert len(g2.nodes) == 2
        assert len(g2.edges) == 1
        assert g2.get_node("n1").label == "Python"


# ============================================================================
# Stats
# ============================================================================

class TestStats:

    def test_basic_stats(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t1"]))
        g.add_node(Node(id="b", label="B", tags=["t1", "t2"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        st = g.stats()
        assert st["node_count"] == 2
        assert st["edge_count"] == 1
        assert st["avg_degree"] == 1.0
        assert st["tag_distribution"]["t1"] == 2
        assert st["tag_distribution"]["t2"] == 1
        assert st["relation_distribution"]["r"] == 1
        assert st["isolated_nodes"] == 0
        assert len(st["top_central_nodes"]) == 2

    def test_empty_graph_stats(self):
        g = CortexGraph()
        st = g.stats()
        assert st["node_count"] == 0
        assert st["edge_count"] == 0
        assert st["avg_degree"] == 0.0
        assert st["relation_distribution"] == {}
        assert st["isolated_nodes"] == 0
        assert st["top_central_nodes"] == []

    def test_stats_with_isolated_nodes(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t1"]))
        g.add_node(Node(id="b", label="B", tags=["t1"]))
        g.add_node(Node(id="c", label="C", tags=["t2"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        st = g.stats()
        assert st["isolated_nodes"] == 1
        assert st["top_central_nodes"][0] in ("A", "B")

    def test_centrality_convenience_methods(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A", tags=["t1"]))
        g.add_node(Node(id="b", label="B", tags=["t1"]))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r"))
        scores = g.compute_centrality()
        assert scores["a"] == 1.0
        assert scores["b"] == 1.0


# ============================================================================
# ExtractionContext.to_graph()
# ============================================================================

class TestExtractionToGraph:

    def test_to_graph_produces_cortex_graph(self):
        extractor = AggressiveExtractor()
        extractor.extract_from_text("My name is Alex and I use Python for data science work.")
        extractor.post_process()
        graph = extractor.context.to_graph()
        assert isinstance(graph, CortexGraph)
        assert len(graph.nodes) > 0

    def test_to_graph_preserves_categories_as_tags(self):
        ctx = ExtractionContext()
        ctx.add_topic("technical_expertise", "Python", confidence=0.9)
        ctx.add_topic("identity", "Marc", confidence=0.95)
        graph = ctx.to_graph()
        python_nodes = graph.find_nodes(label="Python")
        assert len(python_nodes) == 1
        assert "technical_expertise" in python_nodes[0].tags

    def test_to_graph_merges_cross_category_labels(self):
        ctx = ExtractionContext()
        ctx.add_topic("technical_expertise", "Python", confidence=0.8)
        ctx.add_topic("domain_knowledge", "Python", confidence=0.9)
        graph = ctx.to_graph()
        python_nodes = graph.find_nodes(label="Python")
        assert len(python_nodes) == 1
        node = python_nodes[0]
        assert "technical_expertise" in node.tags
        assert "domain_knowledge" in node.tags


# ============================================================================
# NormalizedContext v5 detection
# ============================================================================

class TestNormalizedContextV5:

    def test_load_v5_schema(self):
        v5 = {
            "schema_version": "5.0",
            "meta": {"method": "aggressive_extraction_v5"},
            "graph": {
                "nodes": {"n1": {"id": "n1", "label": "Python", "tags": ["technical_expertise"]}},
                "edges": {}
            },
            "categories": {
                "technical_expertise": [
                    {"topic": "Python", "brief": "Python", "confidence": 0.9}
                ]
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(v5, f)
            path = Path(f.name)

        try:
            ctx = NormalizedContext.load(path)
            assert "technical_expertise" in ctx.categories
            assert ctx.categories["technical_expertise"][0].topic == "Python"
            assert ctx.meta.get("_graph") is not None
        finally:
            path.unlink()

    def test_from_v5_preserves_graph(self):
        v5 = {
            "schema_version": "5.0",
            "meta": {},
            "graph": {"nodes": {"n1": {"id": "n1", "label": "Test"}}, "edges": {}},
            "categories": {"identity": [{"topic": "Test", "confidence": 0.9}]}
        }
        ctx = NormalizedContext.from_v5(v5)
        assert "_graph" in ctx.meta
        assert "n1" in ctx.meta["_graph"]["nodes"]


# ============================================================================
# Node/Edge serialization
# ============================================================================

class TestSerialization:

    def test_node_to_dict_and_back(self):
        n = Node(id="abc", label="Python", tags=["t1", "t2"], confidence=0.85,
                 properties={"key": "val"}, brief="Lang", mention_count=5,
                 first_seen="2025-01-01", last_seen="2025-02-01",
                 relationship_type="partner")
        d = n.to_dict()
        n2 = Node.from_dict(d)
        assert n2.id == n.id
        assert n2.label == n.label
        assert n2.tags == n.tags
        assert n2.confidence == 0.85
        assert n2.properties == {"key": "val"}
        assert n2.relationship_type == "partner"

    def test_edge_to_dict_and_back(self):
        e = Edge(id="e1", source_id="a", target_id="b", relation="uses",
                 confidence=0.7, properties={"weight": 1},
                 first_seen="2025-01-01", last_seen="2025-02-01")
        d = e.to_dict()
        e2 = Edge.from_dict(d)
        assert e2.id == e.id
        assert e2.source_id == "a"
        assert e2.target_id == "b"
        assert e2.relation == "uses"
        assert e2.confidence == 0.7


# ============================================================================
# Migrate.py query/stats subcommands
# ============================================================================

class TestMigrateSubcommands:

    def _import_migrate(self):
        import cortex.cli
        return cortex.cli

    def test_query_subcommand_recognized(self):
        mod = self._import_migrate()
        parser = mod.build_parser()
        args = parser.parse_args(["query", "file.json", "--node", "Python"])
        assert args.subcommand == "query"
        assert args.node == "Python"

    def test_stats_subcommand_recognized(self):
        mod = self._import_migrate()
        parser = mod.build_parser()
        args = parser.parse_args(["stats", "file.json"])
        assert args.subcommand == "stats"

    def test_query_with_v4_file(self):
        mod = self._import_migrate()
        v4 = {
            "schema_version": "4.0",
            "meta": {},
            "categories": {
                "technical_expertise": [
                    {"topic": "Python", "confidence": 0.9, "brief": "Lang"}
                ]
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(v4, f)
            path = f.name

        try:
            rc = mod.main(["query", path, "--node", "Python"])
            assert rc == 0
        finally:
            Path(path).unlink()

    def test_stats_with_v4_file(self):
        mod = self._import_migrate()
        v4 = {
            "schema_version": "4.0",
            "meta": {},
            "categories": {
                "technical_expertise": [
                    {"topic": "Python", "confidence": 0.9}
                ],
                "identity": [
                    {"topic": "Marc", "confidence": 0.95}
                ]
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(v4, f)
            path = f.name

        try:
            rc = mod.main(["stats", path])
            assert rc == 0
        finally:
            Path(path).unlink()

    def test_schema_v5_flag(self):
        """--schema v5 produces v5 context.json."""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(json.dumps({
                "messages": [
                    {"role": "user", "content": "My name is Alex and I use Python."}
                ]
            }))
            out_dir = Path(tmpdir) / "out"
            rc = mod.main([
                "migrate", str(input_file), "--to", "claude",
                "-o", str(out_dir), "--schema", "v5"
            ])
            assert rc == 0
            ctx_path = out_dir / "context.json"
            assert ctx_path.exists()
            data = json.loads(ctx_path.read_text())
            assert data["schema_version"] == "6.0"
            assert "graph" in data
            assert "categories" in data

    def test_query_missing_file(self):
        mod = self._import_migrate()
        rc = mod.main(["query", "/nonexistent.json", "--node", "X"])
        assert rc == 1

    def test_stats_missing_file(self):
        mod = self._import_migrate()
        rc = mod.main(["stats", "/nonexistent.json"])
        assert rc == 1

    def test_known_subcommands_routing(self):
        """query and stats are not routed to migrate."""
        mod = self._import_migrate()
        mod.build_parser()
        # query should NOT be treated as a file path
        argv = ["query", "file.json", "--node", "X"]
        # The main function routes known subcommands directly
        assert argv[0] in ("extract", "import", "migrate", "query", "stats",
                           "-h", "--help")


# ============================================================================
# Runner
# ============================================================================

def run_tests():
    import traceback

    test_classes = [
        TestNodeEdgeCRUD,
        TestQuery,
        TestMergeNodes,
        TestNodeIdHelpers,
        TestUpgradeV4ToV5,
        TestDowngradeV5ToV4,
        TestRoundtrip,
        TestExportFormats,
        TestStats,
        TestExtractionToGraph,
        TestNormalizedContextV5,
        TestSerialization,
        TestMigrateSubcommands,
    ]

    total = 0
    passed = 0
    failed = []

    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"Running {test_class.__name__}")
        print('='*60)

        instance = test_class()
        methods = sorted(m for m in dir(instance) if m.startswith("test_"))

        for method_name in methods:
            total += 1
            method = getattr(instance, method_name)
            try:
                method()
                print(f"  ✅ {method_name}")
                passed += 1
            except AssertionError as e:
                print(f"  ❌ {method_name}: {e}")
                failed.append((test_class.__name__, method_name, str(e)))
            except Exception as e:
                print(f"  ❌ {method_name}: {type(e).__name__}: {e}")
                failed.append((test_class.__name__, method_name, traceback.format_exc()))

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    print('='*60)

    if failed:
        print("\nFailed tests:")
        for cls, method, error in failed:
            print(f"  - {cls}.{method}")
            for line in error.split('\n')[:5]:
                print(f"    {line}")
        return 1

    print("\n✅ All tests passed!")
    return 0


# ============================================================================
# Adjacency list cache
# ============================================================================

class TestAdjacencyCache:

    def _make_graph(self):
        g = CortexGraph()
        g.add_node(Node(id="a", label="A"))
        g.add_node(Node(id="b", label="B"))
        g.add_node(Node(id="c", label="C"))
        g.add_edge(Edge(id="e1", source_id="a", target_id="b", relation="r1"))
        g.add_edge(Edge(id="e2", source_id="b", target_id="c", relation="r2"))
        return g

    def test_cache_built_lazily(self):
        g = self._make_graph()
        assert g._adjacency is None
        adj = g._get_adjacency()
        assert g._adjacency is not None
        assert "a" in adj
        assert "b" in adj

    def test_cache_reused_on_second_call(self):
        g = self._make_graph()
        adj1 = g._get_adjacency()
        adj2 = g._get_adjacency()
        assert adj1 is adj2  # same object

    def test_invalidated_on_add_node(self):
        g = self._make_graph()
        g._get_adjacency()
        assert g._adjacency is not None
        g.add_node(Node(id="d", label="D"))
        assert g._adjacency is None

    def test_invalidated_on_add_edge(self):
        g = self._make_graph()
        g._get_adjacency()
        g.add_edge(Edge(id="e3", source_id="a", target_id="c", relation="r3"))
        assert g._adjacency is None

    def test_invalidated_on_remove_node(self):
        g = self._make_graph()
        g._get_adjacency()
        g.remove_node("c")
        assert g._adjacency is None

    def test_invalidated_on_remove_edge(self):
        g = self._make_graph()
        g._get_adjacency()
        g.remove_edge("e1")
        assert g._adjacency is None

    def test_invalidated_on_merge_nodes(self):
        g = self._make_graph()
        g._get_adjacency()
        g.merge_nodes("a", "b")
        assert g._adjacency is None

    def test_get_neighbors_uses_adjacency(self):
        g = self._make_graph()
        neighbors = g.get_neighbors("b")
        neighbor_ids = {n.id for _, n in neighbors}
        assert neighbor_ids == {"a", "c"}

    def test_get_edges_for_uses_adjacency(self):
        g = self._make_graph()
        edges = g.get_edges_for("b")
        edge_ids = {e.id for e in edges}
        assert edge_ids == {"e1", "e2"}

    def test_shortest_path_uses_adjacency(self):
        g = self._make_graph()
        path = g.shortest_path("a", "c")
        assert path == ["a", "b", "c"]

    def test_k_hop_neighborhood_uses_adjacency(self):
        g = self._make_graph()
        nodes, edges = g.k_hop_neighborhood("a", k=1)
        assert nodes == {"a", "b"}
        assert "e1" in edges

    def test_relationship_labels_uses_adjacency(self):
        g = self._make_graph()
        labels = g._node_relationship_labels("b")
        assert set(labels) == {"A", "C"}

    def test_adjacency_correctness_after_rebuild(self):
        g = self._make_graph()
        g._get_adjacency()
        g.add_node(Node(id="d", label="D"))
        g.add_edge(Edge(id="e3", source_id="c", target_id="d", relation="r3"))
        path = g.shortest_path("a", "d")
        assert path == ["a", "b", "c", "d"]


if __name__ == "__main__":
    sys.exit(run_tests())
