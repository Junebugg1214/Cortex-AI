"""
Tests for UPAI Phase 3: Version Control

Covers:
- Commit creates version in store
- Correct version_id (SHA-256 hash)
- Commit with identity adds signature
- Log returns versions newest-first
- Log respects limit
- Diff shows added/removed/modified nodes
- Diff with identical versions shows no changes
- Checkout restores exact graph state
- Head returns latest version
- Head returns None on empty store
- Multiple commits chain parent_ids
- Store directory created on first commit
"""

import tempfile
from pathlib import Path

from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity
from cortex.upai.versioning import ContextVersion, VersionStore


def _sample_graph(label_suffix: str = "") -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label=f"Python{label_suffix}",
                    tags=["technical_expertise"], confidence=0.9))
    g.add_node(Node(id="n2", label=f"Healthcare{label_suffix}",
                    tags=["domain_knowledge"], confidence=0.8))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="used_in"))
    return g


class TestVersionStore:

    def test_commit_creates_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            graph = _sample_graph()
            version = store.commit(graph, "Initial commit")
            assert version.version_id
            assert version.message == "Initial commit"
            assert version.source == "manual"
            assert version.node_count == 2
            assert version.edge_count == 1
            assert version.parent_id is None

    def test_commit_version_id_is_hash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            graph = _sample_graph()
            version = store.commit(graph, "test")
            assert len(version.version_id) == 32  # first 32 chars of SHA-256
            # version_id should be hex
            int(version.version_id, 16)

    def test_commit_with_identity_adds_signature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            identity = UPAIIdentity.generate("Test")
            graph = _sample_graph()
            version = store.commit(graph, "signed commit", identity=identity)
            assert version.signature is not None
            assert len(version.signature) > 0

    def test_log_returns_newest_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            g1 = _sample_graph()
            g2 = _sample_graph(" v2")
            store.commit(g1, "first")
            store.commit(g2, "second")
            versions = store.log()
            assert len(versions) == 2
            assert versions[0].message == "second"
            assert versions[1].message == "first"

    def test_log_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            for i in range(5):
                g = _sample_graph(f" {i}")
                store.commit(g, f"commit {i}")
            versions = store.log(limit=3)
            assert len(versions) == 3
            assert versions[0].message == "commit 4"

    def test_diff_shows_added_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")

            g1 = CortexGraph()
            g1.add_node(Node(id="n1", label="Python", tags=["tech"], confidence=0.9))
            v1 = store.commit(g1, "v1")

            g2 = CortexGraph()
            g2.add_node(Node(id="n2", label="React", tags=["tech"], confidence=0.8))
            v2 = store.commit(g2, "v2")

            d = store.diff(v1.version_id, v2.version_id)
            assert "n2" in d["added"]
            assert "n1" in d["removed"]

    def test_diff_shows_modified_nodes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")

            g1 = CortexGraph()
            g1.add_node(Node(id="n1", label="Python", tags=["tech"], confidence=0.7))
            v1 = store.commit(g1, "v1")

            g2 = CortexGraph()
            g2.add_node(Node(id="n1", label="Python", tags=["tech", "language"], confidence=0.9))
            v2 = store.commit(g2, "v2")

            d = store.diff(v1.version_id, v2.version_id)
            assert len(d["modified"]) == 1
            mod = d["modified"][0]
            assert mod["node_id"] == "n1"
            assert "confidence" in mod["changes"]
            assert mod["changes"]["confidence"]["from"] == 0.7
            assert mod["changes"]["confidence"]["to"] == 0.9

    def test_diff_identical_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            g = _sample_graph()
            v1 = store.commit(g, "same")
            # Same graph, different commit
            d = store.diff(v1.version_id, v1.version_id)
            assert d["added"] == []
            assert d["removed"] == []
            assert d["modified"] == []

    def test_checkout_restores_graph(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            graph = _sample_graph()
            version = store.commit(graph, "checkpoint")

            restored = store.checkout(version.version_id)
            assert len(restored.nodes) == 2
            assert len(restored.edges) == 1
            assert restored.nodes["n1"].label == "Python"
            assert restored.nodes["n2"].label == "Healthcare"

    def test_head_returns_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            g1 = _sample_graph()
            g2 = _sample_graph(" v2")
            store.commit(g1, "first")
            store.commit(g2, "second")
            head = store.head()
            assert head is not None
            assert head.message == "second"

    def test_head_returns_none_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            assert store.head() is None

    def test_parent_ids_chain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            g1 = _sample_graph()
            g2 = _sample_graph(" v2")
            g3 = _sample_graph(" v3")
            v1 = store.commit(g1, "first")
            v2 = store.commit(g2, "second")
            v3 = store.commit(g3, "third")
            assert v1.parent_id is None
            assert v2.parent_id == v1.version_id
            assert v3.parent_id == v2.version_id

    def test_store_directory_created_on_commit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir) / "new_store" / ".cortex"
            assert not store_dir.exists()
            store = VersionStore(store_dir)
            store.commit(_sample_graph(), "init")
            assert store_dir.exists()
            assert (store_dir / "versions").exists()
            assert (store_dir / "history.json").exists()

    def test_context_version_serialization(self):
        v = ContextVersion(
            version_id="abc123",
            parent_id="parent1",
            timestamp="2025-01-01T00:00:00Z",
            source="extraction",
            message="test message",
            graph_hash="deadbeef",
            node_count=5,
            edge_count=3,
            signature="sig123",
        )
        d = v.to_dict()
        v2 = ContextVersion.from_dict(d)
        assert v2.version_id == v.version_id
        assert v2.parent_id == v.parent_id
        assert v2.message == v.message
        assert v2.signature == v.signature

    def test_commit_with_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            graph = _sample_graph()
            version = store.commit(graph, "from extraction", source="extraction")
            assert version.source == "extraction"
