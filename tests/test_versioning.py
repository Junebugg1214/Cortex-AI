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

import hashlib
import json
from pathlib import Path
import tempfile

from cortex.integrity import check_store_integrity
from cortex.graph import CortexGraph, Edge, Node
from cortex.upai.identity import UPAIIdentity
from cortex.upai.versioning import ContextVersion, VersionStore


def _sample_graph(label_suffix: str = "") -> CortexGraph:
    g = CortexGraph()
    g.add_node(Node(id="n1", label=f"Python{label_suffix}", tags=["technical_expertise"], confidence=0.9))
    g.add_node(Node(id="n2", label=f"Healthcare{label_suffix}", tags=["domain_knowledge"], confidence=0.8))
    g.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="used_in"))
    return g


def _sample_graph_with_provenance(label_suffix: str = "") -> CortexGraph:
    graph = _sample_graph(label_suffix)
    for node in graph.nodes.values():
        node.provenance = [{"source": "test-source", "method": "test"}]
    return graph


def _write_legacy_commit(store_dir: Path, graph: CortexGraph, message: str, parent_id: str | None = None) -> dict:
    graph_data = graph.export_v5()
    graph_json = json.dumps(graph_data, sort_keys=True, ensure_ascii=False)
    graph_hash = hashlib.sha256(graph_json.encode("utf-8")).hexdigest()
    version_id = graph_hash[:32]
    (store_dir / "versions").mkdir(parents=True, exist_ok=True)
    (store_dir / "versions" / f"{version_id}.json").write_text(json.dumps(graph_data, indent=2), encoding="utf-8")
    return {
        "version_id": version_id,
        "parent_id": parent_id,
        "merge_parent_ids": [],
        "timestamp": "2026-01-01T00:00:00+00:00",
        "branch": "main",
        "source": "manual",
        "message": message,
        "graph_hash": graph_hash,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "signature": None,
    }


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
            assert version.chain_hash_version == 2

    def test_identical_graph_hash_with_different_parents_produces_different_version_ids(self):
        graph_hash = "a" * 64
        common = {
            "graph_hash": graph_hash,
            "merge_parent_ids": [],
            "branch": "main",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "source": "manual",
            "message": "same graph",
        }

        first = VersionStore.derive_version_id(parent_id="parent-a", **common)
        second = VersionStore.derive_version_id(parent_id="parent-b", **common)

        assert first != second

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

    def test_diff_shows_temporal_field_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")

            g1 = CortexGraph()
            g1.add_node(
                Node(id="n1", label="Project Atlas", tags=["tech"], status="planned", valid_from="2026-01-01T00:00:00Z")
            )
            v1 = store.commit(g1, "v1")

            g2 = CortexGraph()
            g2.add_node(
                Node(
                    id="n1",
                    label="Project Atlas",
                    tags=["tech"],
                    status="active",
                    valid_from="2026-02-01T00:00:00Z",
                    valid_to="2026-12-31T00:00:00Z",
                )
            )
            v2 = store.commit(g2, "v2")

            d = store.diff(v1.version_id, v2.version_id)
            assert len(d["modified"]) == 1
            mod = d["modified"][0]
            assert mod["changes"]["status"]["from"] == "planned"
            assert mod["changes"]["status"]["to"] == "active"
            assert mod["changes"]["valid_from"]["from"] == "2026-01-01T00:00:00Z"
            assert mod["changes"]["valid_to"]["to"] == "2026-12-31T00:00:00Z"
            assert any(change["type"] == "lifecycle_shift" for change in d["semantic_changes"])

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

    def test_resolve_at_returns_latest_version_before_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            v1 = store.commit(_sample_graph(), "first")
            v2 = store.commit(_sample_graph(" v2"), "second")

            resolved = store.resolve_at(v1.timestamp)

            assert resolved == v1.version_id
            assert resolved != v2.version_id

    def test_is_ancestor_detects_branch_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            v1 = store.commit(_sample_graph(), "first")
            store.create_branch("feature/demo")
            store.switch_branch("feature/demo")
            v2 = store.commit(_sample_graph(" v2"), "second")

            assert store.is_ancestor(v1.version_id, v2.version_id) is True
            assert store.is_ancestor(v2.version_id, v1.version_id) is False

    def test_lineage_records_include_branch_ancestry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            v1 = store.commit(_sample_graph(), "first")
            store.create_branch("feature/demo")
            store.switch_branch("feature/demo")
            v2 = store.commit(_sample_graph(" v2"), "second")

            records = store.lineage_records("feature/demo")

            assert [item["version_id"] for item in records] == [v1.version_id, v2.version_id]

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
            merge_parent_ids=["parent2"],
            timestamp="2025-01-01T00:00:00Z",
            branch="main",
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
        assert v2.merge_parent_ids == v.merge_parent_ids
        assert v2.branch == v.branch
        assert v2.message == v.message
        assert v2.signature == v.signature
        assert v2.chain_hash_version == 2

    def test_rehash_migration_produces_store_that_passes_integrity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir) / ".cortex"
            first = _write_legacy_commit(store_dir, _sample_graph_with_provenance(), "legacy first")
            second = _write_legacy_commit(
                store_dir,
                _sample_graph_with_provenance(" v2"),
                "legacy second",
                parent_id=first["version_id"],
            )
            (store_dir / "history.json").write_text(json.dumps([first, second], indent=2), encoding="utf-8")
            (store_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
            (store_dir / "refs" / "heads" / "main").write_text(second["version_id"], encoding="utf-8")
            (store_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

            store = VersionStore(store_dir)
            result = store.rehash_chain_v2(confirm=True)
            integrity = check_store_integrity(store_dir)

            assert result["status"] == "ok"
            assert result["mapping"][first["version_id"]] != first["version_id"]
            assert store.resolve_ref("HEAD") == result["mapping"][second["version_id"]]
            assert integrity["status"] == "ok"
            assert integrity["chain_integrity"]["chain_hash_version"] == 2
            assert integrity["chain_integrity"]["legacy_unchained"] is False
            assert (store_dir / "migrations" / "rehash-v2.log").exists()

    def test_store_integrity_detects_intermediate_snapshot_tampering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir) / ".cortex"
            store = VersionStore(store_dir)
            store.commit(_sample_graph(), "first")
            intermediate = store.commit(_sample_graph(" v2"), "second")
            store.commit(_sample_graph(" v3"), "third")
            snapshot_path = store_dir / "versions" / f"{intermediate.version_id}.json"
            payload = json.loads(snapshot_path.read_text())
            payload["graph"]["nodes"]["n1"]["label"] = "Tampered Python"
            snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            integrity = check_store_integrity(store_dir)

            assert integrity["status"] == "error"
            assert any(
                issue["version_id"] == intermediate.version_id
                for issue in integrity["snapshot_integrity_issues"]
            )

    def test_commit_with_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            graph = _sample_graph()
            version = store.commit(graph, "from extraction", source="extraction")
            assert version.source == "extraction"

    def test_blame_node_tracks_introduction_and_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")

            g1 = CortexGraph()
            g1.add_node(
                Node(
                    id="n1",
                    label="PostgreSQL",
                    aliases=["postgres"],
                    tags=["technical_expertise"],
                    confidence=0.8,
                    provenance=[{"source": "import-a", "method": "extract"}],
                )
            )
            v1 = store.commit(g1, "initial memory", source="extraction")

            g2 = CortexGraph()
            g2.add_node(
                Node(
                    id="n1",
                    label="PostgreSQL",
                    aliases=["postgres"],
                    tags=["technical_expertise"],
                    confidence=0.95,
                    status="active",
                    valid_from="2026-01-01T00:00:00Z",
                    provenance=[{"source": "manual-a", "method": "manual"}],
                )
            )
            v2 = store.commit(g2, "promote postgres", source="manual")

            blame = store.blame_node(
                node_id="n1",
                label="PostgreSQL",
                aliases=["postgres"],
                canonical_id="n1",
                limit=10,
            )

            assert blame["versions_seen"] == 2
            assert blame["introduced_in"]["version_id"] == v1.version_id
            assert blame["last_seen_in"]["version_id"] == v2.version_id
            assert blame["versions_changed"] == 2
            assert blame["history"][0]["node"]["provenance_sources"] == ["import-a"]
            assert blame["history"][1]["node"]["status"] == "active"

    def test_blame_node_filters_by_ref_and_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")

            base = CortexGraph()
            base.add_node(
                Node(
                    id="n1",
                    label="PostgreSQL",
                    aliases=["postgres"],
                    tags=["technical_expertise"],
                    provenance=[{"source": "import-a", "method": "extract"}],
                )
            )
            store.commit(base, "base")

            store.create_branch("feature/db")
            store.switch_branch("feature/db")
            feature = CortexGraph()
            feature.add_node(
                Node(
                    id="n1",
                    label="PostgreSQL",
                    aliases=["postgres"],
                    tags=["technical_expertise"],
                    confidence=0.95,
                    provenance=[{"source": "manual-a", "method": "manual"}],
                    status="active",
                )
            )
            store.commit(feature, "feature promote")

            store.switch_branch("main")
            main = CortexGraph()
            main.add_node(
                Node(
                    id="n1",
                    label="PostgreSQL",
                    aliases=["postgres"],
                    tags=["technical_expertise"],
                    confidence=0.8,
                    provenance=[{"source": "import-a", "method": "extract"}],
                )
            )
            store.commit(main, "main steady")

            blame = store.blame_node(
                node_id="n1",
                label="PostgreSQL",
                aliases=["postgres"],
                canonical_id="n1",
                ref="feature/db",
                source="manual-a",
                limit=10,
            )

            assert blame["versions_seen"] == 1
            assert blame["introduced_in"]["message"] == "feature promote"
            assert blame["history"][0]["node"]["provenance_sources"] == ["manual-a"]

    def test_branch_bootstraps_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")
            version = store.commit(_sample_graph(), "initial")
            assert store.current_branch() == "main"
            assert store.head("HEAD") is not None
            assert store.head("HEAD").version_id == version.version_id
            assert store.resolve_ref("main") == version.version_id

    def test_branch_create_switch_and_log_follow_ref_ancestry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VersionStore(Path(tmpdir) / ".cortex")

            main_v1 = store.commit(_sample_graph(), "main-1")
            store.create_branch("feature/atlas")
            store.switch_branch("feature/atlas")
            feature_v1 = store.commit(_sample_graph(" feature"), "feature-1")

            store.switch_branch("main")
            main_v2 = store.commit(_sample_graph(" main"), "main-2")

            feature_log = store.log(limit=10, ref="feature/atlas")
            main_log = store.log(limit=10, ref="main")

            assert feature_log[0].version_id == feature_v1.version_id
            assert feature_log[1].version_id == main_v1.version_id
            assert main_log[0].version_id == main_v2.version_id
            assert main_log[1].version_id == main_v1.version_id
            assert store.resolve_ref("feature/atlas") == feature_v1.version_id
