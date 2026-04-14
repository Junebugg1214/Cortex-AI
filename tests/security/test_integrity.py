from __future__ import annotations

from pathlib import Path

from cortex.claims import retract_graph_source, stamp_graph_provenance
from cortex.graph import CortexGraph, Edge, Node
from cortex.integrity import check_graph_integrity, check_store_integrity, graph_checksum
from cortex.sources import SourceRegistry
from cortex.storage import build_sqlite_backend


def _seed_registry(tmp_path: Path, label: str, content: str) -> tuple[SourceRegistry, dict]:
    registry = SourceRegistry.for_store(tmp_path)
    source_path = tmp_path / label
    source_path.write_text(content, encoding="utf-8")
    payload = registry.register_path(source_path, label=label, metadata={"kind": "test"})
    return registry, payload


def test_graph_checksum_is_stable():
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"]))

    assert graph_checksum(graph) == graph_checksum(graph)


def test_check_graph_integrity_detects_orphaned_nodes():
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"]))

    payload = check_graph_integrity(graph)

    assert payload["status"] == "warning"
    assert payload["orphaned_nodes"][0]["id"] == "n1"


def test_check_graph_integrity_detects_broken_edges():
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"], provenance=[{"source": "doc"}]))
    graph.add_edge(Edge(id="e1", source_id="n1", target_id="missing", relation="depends_on"))

    payload = check_graph_integrity(graph)

    assert payload["status"] == "error"
    assert payload["broken_edges"][0]["id"] == "e1"


def test_retract_graph_source_returns_integrity_report(tmp_path: Path):
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"]))
    registry, payload = _seed_registry(tmp_path, "atlas.md", "Atlas launched")
    stamp_graph_provenance(
        graph,
        source=payload["stable_id"],
        stable_source_id=payload["stable_id"],
        source_label="atlas.md",
        method="test",
    )

    result = retract_graph_source(graph, identifier="atlas.md", registry=registry, dry_run=False, confirm=True)

    assert result["integrity"]["status"] == "ok"


def test_check_store_integrity_returns_head_and_status(tmp_path: Path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"], provenance=[{"source": "doc"}]))
    backend.versions.commit(graph, "seed")

    payload = check_store_integrity(store_dir)

    assert payload["status"] == "ok"
    assert payload["head"]
    assert payload["graph_integrity"]["status"] == "ok"
