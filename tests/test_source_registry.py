from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex.claims import RetractionPlanningError, retract_graph_source, stamp_graph_provenance
from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory import AggressiveExtractor
from cortex.cli import main
from cortex.graph import CortexGraph, Edge, Node, ensure_provenance, make_edge_id, make_node_id
from cortex.minds import adopt_graph_into_mind, init_mind, load_mind_core_graph
from cortex.sources import (
    AmbiguousSourceLabelError,
    DuplicateSourceError,
    SourceRecord,
    SourceRegistry,
    stable_source_id_for_bytes,
)


def _registry(store_dir: Path) -> SourceRegistry:
    return SourceRegistry.for_store(store_dir)


def _source_graph(*, stable_id: str, label: str) -> CortexGraph:
    graph = CortexGraph()
    left = Node(id=make_node_id("Policy memo"), label="Policy memo", tags=["business_context"], confidence=0.9)
    right = Node(id=make_node_id("Atlas service"), label="Atlas service", tags=["active_priorities"], confidence=0.8)
    graph.add_node(left)
    graph.add_node(right)
    edge = Edge(
        id=make_edge_id(left.id, right.id, "supports"),
        source_id=left.id,
        target_id=right.id,
        relation="supports",
        confidence=0.7,
    )
    graph.add_edge(edge)
    stamp_graph_provenance(
        graph,
        source=stable_id,
        stable_source_id=stable_id,
        source_label=label,
        method="ingest",
    )
    for item in graph.edges.values():
        item.provenance.append(
            {
                "source": stable_id,
                "source_id": stable_id,
                "source_label": label,
                "method": "ingest",
            }
        )
    return graph


def test_registering_same_content_under_different_labels_resolves_to_one_stable_id(tmp_path):
    registry = _registry(tmp_path)
    payload_a = registry.register_bytes(b"Atlas launched", label="incident-a.md")
    payload_b = registry.register_bytes(b"Atlas launched", label="incident-b.md", force_reingest=True)

    assert payload_a["stable_id"] == payload_b["stable_id"]
    assert payload_b["duplicate"] is True
    assert sorted(payload_b["labels"]) == ["incident-a.md", "incident-b.md"]


def test_duplicate_ingest_without_force_is_blocked(tmp_path):
    registry = _registry(tmp_path)
    registry.register_bytes(b"Atlas launched", label="incident-a.md")

    with pytest.raises(DuplicateSourceError) as exc:
        registry.register_bytes(b"Atlas launched", label="incident-b.md")

    assert "force_reingest=True" in str(exc.value)


def test_normalized_content_hash_ignores_trailing_whitespace(tmp_path):
    registry = _registry(tmp_path)
    payload_a = registry.register_bytes(b"Atlas launched\n", label="incident-a.md")
    payload_b = registry.register_bytes(b"Atlas launched   \n\n", label="incident-b.md", force_reingest=True)

    assert payload_a["stable_id"] == payload_b["stable_id"]


def test_stable_source_id_matches_direct_hash_helper():
    assert stable_source_id_for_bytes(b"Atlas launched") == stable_source_id_for_bytes(b"Atlas launched")


def test_resolve_by_stable_id_returns_record(tmp_path):
    registry = _registry(tmp_path)
    payload = registry.register_bytes(b"Atlas launched", label="incident-a.md")

    record = registry.resolve(payload["stable_id"])

    assert isinstance(record, SourceRecord)
    assert record.stable_id == payload["stable_id"]
    assert record.labels == ["incident-a.md"]


def test_resolve_by_human_label_returns_record(tmp_path):
    registry = _registry(tmp_path)
    payload = registry.register_bytes(b"Atlas launched", label="incident-a.md")

    record = registry.resolve("incident-a.md")

    assert record.stable_id == payload["stable_id"]


def test_ambiguous_label_resolution_raises_named_error(tmp_path):
    registry = _registry(tmp_path)
    registry.register_bytes(b"Atlas launched", label="Policy Memo")
    registry.register_bytes(b"Atlas archived", label="Policy Memo")

    with pytest.raises(AmbiguousSourceLabelError) as exc:
        registry.resolve("policy memo")

    assert "ambiguous" in str(exc.value).lower()


def test_retraction_by_human_label_resolves_to_correct_stable_id(tmp_path):
    store_dir = tmp_path / ".cortex"
    registry = _registry(store_dir)
    payload = registry.register_bytes(b"Atlas launched", label="incident-a.md")
    graph = _source_graph(stable_id=payload["stable_id"], label="incident-a.md")

    plan = retract_graph_source(graph, identifier="incident-a.md", registry=registry, dry_run=True)

    assert plan["stable_source_id"] == payload["stable_id"]
    assert plan["labels"] == ["incident-a.md"]
    assert len(plan["pruned_nodes"]) == 2


def test_ambiguous_label_retraction_is_refused_with_clear_error(tmp_path):
    store_dir = tmp_path / ".cortex"
    registry = _registry(store_dir)
    left = registry.register_bytes(b"Atlas launched", label="Policy Memo")
    right = registry.register_bytes(b"Atlas archived", label="Policy Memo")
    graph = _source_graph(stable_id=left["stable_id"], label="Policy Memo")
    other = _source_graph(stable_id=right["stable_id"], label="Policy Memo")
    for node in other.nodes.values():
        graph.add_node(node)

    with pytest.raises(RetractionPlanningError) as exc:
        retract_graph_source(graph, identifier="Policy Memo", registry=registry, dry_run=True)

    assert "ambiguous" in str(exc.value).lower()
    assert left["stable_id"] in str(exc.value)
    assert right["stable_id"] in str(exc.value)


def test_dry_run_reports_prune_set_without_modifying_graph(tmp_path):
    store_dir = tmp_path / ".cortex"
    registry = _registry(store_dir)
    payload = registry.register_bytes(b"Atlas launched", label="incident-a.md")
    graph = _source_graph(stable_id=payload["stable_id"], label="incident-a.md")
    before = graph.export_v5()

    plan = retract_graph_source(graph, identifier=payload["stable_id"], registry=registry, dry_run=True)

    assert plan["dry_run"] is True
    assert len(plan["pruned_nodes"]) == 2
    assert len(plan["pruned_edges"]) == 1
    assert graph.export_v5()["graph"] == before["graph"]


def test_renamed_source_does_not_orphan_fact_lineage(tmp_path):
    store_dir = tmp_path / ".cortex"
    registry = _registry(store_dir)
    payload = registry.register_bytes(b"Atlas launched", label="incident-a.md")
    registry.register_bytes(b"Atlas launched", label="incident-renamed.md", force_reingest=True)
    graph = _source_graph(stable_id=payload["stable_id"], label="incident-a.md")

    result = retract_graph_source(
        graph,
        identifier="incident-renamed.md",
        registry=registry,
        dry_run=False,
        confirm=True,
    )

    assert result["stable_source_id"] == payload["stable_id"]
    assert graph.nodes == {}
    assert graph.edges == {}


def test_sources_list_cli_returns_stable_ids_for_a_mind(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    registry = _registry(store_dir)
    init_mind(store_dir, "ops", owner="tester")
    payload = registry.register_bytes(b"Atlas launched", label="incident-a.md")
    adopt_graph_into_mind(store_dir, "ops", _source_graph(stable_id=payload["stable_id"], label="incident-a.md"))

    rc = main(["sources", "list", "--mind", "ops", "--store-dir", str(store_dir), "--format", "json"])
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["source_count"] == 1
    assert output["sources"][0]["stable_id"] == payload["stable_id"]
    assert output["sources"][0]["labels"] == ["incident-a.md"]


def test_sources_retract_cli_dry_run_reports_prune_set_and_preserves_graph(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    registry = _registry(store_dir)
    init_mind(store_dir, "ops", owner="tester")
    payload = registry.register_bytes(b"Atlas launched", label="incident-a.md")
    adopt_graph_into_mind(store_dir, "ops", _source_graph(stable_id=payload["stable_id"], label="incident-a.md"))
    before = load_mind_core_graph(store_dir, "ops")["graph"].export_v5()

    rc = main(
        [
            "sources",
            "retract",
            "incident-a.md",
            "--mind",
            "ops",
            "--dry-run",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    after = load_mind_core_graph(store_dir, "ops")["graph"].export_v5()

    assert rc == 0
    assert output["dry_run"] is True
    assert len(output["pruned_nodes"]) == 2
    assert len(output["pruned_edges"]) == 1
    assert before == after


def test_retract_is_total(tmp_path):
    store_dir = tmp_path / ".cortex"
    registry = _registry(store_dir)
    source_text = (
        "I am a Python developer. I use Python and React. "
        "I work in healthcare AI. My current priority is building Atlas service."
    )
    payload = registry.register_bytes(source_text.encode("utf-8"), label="profile.txt")
    extractor = AggressiveExtractor(extractor_run_id=payload["stable_id"])
    extracted = extractor.process_plain_text(source_text)
    graph = upgrade_v4_to_v5(extracted)

    assert graph.nodes
    assert ensure_provenance(graph) == []

    retract_graph_source(
        graph,
        identifier="profile.txt",
        registry=registry,
        dry_run=False,
        confirm=True,
    )

    source_id = payload["stable_id"]
    residual_node_refs = [
        node.id
        for node in graph.nodes.values()
        if any(item.get("source_id") == source_id or item.get("source") == source_id for item in node.provenance)
    ]
    residual_edge_refs = [
        edge.id
        for edge in graph.edges.values()
        if any(item.get("source_id") == source_id or item.get("source") == source_id for item in edge.provenance)
    ]
    assert residual_node_refs == []
    assert residual_edge_refs == []
    assert ensure_provenance(graph) == []
