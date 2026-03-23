import tempfile
from pathlib import Path

from cortex.graph import CortexGraph, Node, make_node_id
from cortex.merge import merge_refs
from cortex.upai.versioning import VersionStore


def _graph_with_nodes(*nodes: Node) -> CortexGraph:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    return graph


def test_merge_refs_combines_non_conflicting_branch_changes():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VersionStore(Path(tmpdir) / ".cortex")

        python = Node(id=make_node_id("Python"), label="Python", tags=["technical_expertise"], confidence=0.9)
        base = store.commit(_graph_with_nodes(python), "base")

        store.create_branch("feature/atlas")
        store.switch_branch("feature/atlas")
        atlas = Node(id=make_node_id("Project Atlas"), label="Project Atlas", tags=["active_priorities"], confidence=0.8)
        feature = store.commit(_graph_with_nodes(python, atlas), "feature add atlas")

        store.switch_branch("main")
        rust = Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise"], confidence=0.7)
        main = store.commit(_graph_with_nodes(python, rust), "main add rust")

        result = merge_refs(store, "HEAD", "feature/atlas")

        assert result.ok
        assert result.base_version == base.version_id
        assert result.current_version == main.version_id
        assert result.other_version == feature.version_id
        assert make_node_id("Rust") in result.merged.nodes
        assert make_node_id("Project Atlas") in result.merged.nodes


def test_merge_refs_detects_conflicting_temporal_edits():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VersionStore(Path(tmpdir) / ".cortex")

        atlas_id = make_node_id("Project Atlas")
        base_node = Node(id=atlas_id, label="Project Atlas", tags=["active_priorities"], status="planned")
        store.commit(_graph_with_nodes(base_node), "base")

        store.create_branch("feature/activate")
        store.switch_branch("feature/activate")
        active_node = Node(
            id=atlas_id,
            label="Project Atlas",
            tags=["active_priorities"],
            status="active",
            valid_from="2026-03-01T00:00:00Z",
        )
        store.commit(_graph_with_nodes(active_node), "activate atlas")

        store.switch_branch("main")
        historical_node = Node(
            id=atlas_id,
            label="Project Atlas",
            tags=["active_priorities"],
            status="historical",
            valid_to="2026-02-01T00:00:00Z",
        )
        store.commit(_graph_with_nodes(historical_node), "archive atlas")

        result = merge_refs(store, "HEAD", "feature/activate")

        assert not result.ok
        assert any(conflict.field in {"status", "valid_from", "valid_to"} for conflict in result.conflicts)
