from __future__ import annotations

import json

from cortex.cli import main
from cortex.graph.graph import CortexGraph, Node, make_node_id
from cortex.versioning.merge import CanonicalEntityRegistry, merge_graphs
from cortex.versioning.upai.versioning import VersionStore


def _graph_with_nodes(*nodes: Node) -> CortexGraph:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    return graph


def _entity(label: str, *, brief: str = "", confidence: float = 0.9, aliases: list[str] | None = None) -> Node:
    node_id = make_node_id(label)
    return Node(
        id=node_id,
        label=label,
        tags=["business_context"],
        aliases=list(aliases or []),
        confidence=confidence,
        brief=brief or label,
        canonical_id=node_id,
    )


def test_surface_variants_resolve_to_alias_not_direct_conflict():
    base = CortexGraph()
    current = _graph_with_nodes(_entity("OpenAI"))
    other = _graph_with_nodes(_entity("Open AI"))

    result = merge_graphs(base, current, other)

    assert result.ok
    assert result.summary["conflict_classes"]["ALIAS"] == 1
    assert result.summary["conflict_classes"]["DIRECT"] == 0
    assert len(result.merged.nodes) == 1


def test_alias_resolution_preserves_variant_as_alias():
    result = merge_graphs(CortexGraph(), _graph_with_nodes(_entity("OpenAI")), _graph_with_nodes(_entity("Open AI")))
    node = next(iter(result.merged.nodes.values()))

    assert "Open AI" in node.aliases
    assert node.label == "OpenAI"


def test_novel_entity_is_classified_as_novel():
    current = _graph_with_nodes(_entity("OpenAI"))
    other = _graph_with_nodes(_entity("Anthropic"))

    result = merge_graphs(CortexGraph(), current, other)

    assert result.summary["conflict_classes"]["NOVEL"] == 1
    assert any(item["label"] == "Anthropic" for item in result.summary["novel_entities"])


def test_same_canonical_id_with_different_values_produces_direct_conflict():
    node_id = make_node_id("OpenAI")
    base = _graph_with_nodes(
        Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Base", canonical_id=node_id)
    )
    current = _graph_with_nodes(
        Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Current", canonical_id=node_id)
    )
    other = _graph_with_nodes(
        Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Incoming", canonical_id=node_id)
    )

    result = merge_graphs(base, current, other)

    assert not result.ok
    assert result.summary["conflict_classes"]["DIRECT"] >= 1
    assert any(conflict.field == "brief" and conflict.conflict_class == "DIRECT" for conflict in result.conflicts)


def test_alias_mappings_persist_to_future_merges():
    initial = merge_graphs(CortexGraph(), _graph_with_nodes(_entity("OpenAI")), _graph_with_nodes(_entity("Open AI")))
    future = _graph_with_nodes(_entity("Open A.I.", aliases=["Open AI"]))

    result = merge_graphs(initial.merged, initial.merged, future)

    assert result.summary["conflict_classes"]["ALIAS"] == 1
    assert len(result.merged.nodes) == 1


def test_canonical_entity_registry_matches_existing_aliases():
    node = _entity("OpenAI", aliases=["Open AI"])
    registry = CanonicalEntityRegistry(_graph_with_nodes(node))

    matched = registry.match(_entity("Open AI"))

    assert matched is not None
    assert matched.id == node.id


def test_alias_merge_does_not_create_duplicate_nodes():
    result = merge_graphs(
        CortexGraph(), _graph_with_nodes(_entity("Acme Health")), _graph_with_nodes(_entity("Acme-Health"))
    )

    assert len(result.merged.nodes) == 1
    assert result.summary["conflict_classes"]["ALIAS"] == 1


def test_direct_conflicts_are_exposed_in_merge_preview_cli(tmp_path, capsys):
    store = VersionStore(tmp_path / ".cortex")
    node_id = make_node_id("OpenAI")
    store.commit(_graph_with_nodes(Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Base")), "base")
    store.create_branch("feature/openai")
    store.switch_branch("feature/openai")
    store.commit(
        _graph_with_nodes(Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Incoming")), "incoming"
    )
    store.switch_branch("main")
    store.commit(
        _graph_with_nodes(Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Current")), "current"
    )

    rc = main(
        [
            "merge",
            "preview",
            "--base",
            "main",
            "--incoming",
            "feature/openai",
            "--store-dir",
            str(tmp_path / ".cortex"),
            "--format",
            "json",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert output["summary"]["conflict_classes"]["DIRECT"] >= 1
    assert output["direct_conflicts"]


def test_merge_commit_refuses_unresolved_direct_conflicts(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)
    node_id = make_node_id("OpenAI")
    store.commit(_graph_with_nodes(Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Base")), "base")
    store.create_branch("feature/openai")
    store.switch_branch("feature/openai")
    store.commit(
        _graph_with_nodes(Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Incoming")), "incoming"
    )
    store.switch_branch("main")
    store.commit(
        _graph_with_nodes(Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Current")), "current"
    )

    rc = main(["merge", "commit", "--base", "main", "--incoming", "feature/openai", "--store-dir", str(store_dir)])
    output = capsys.readouterr().out

    assert rc == 1
    assert "unresolved DIRECT conflict" in output


def test_merge_preview_reports_alias_novel_and_direct_classes():
    node_id = make_node_id("OpenAI")
    base = _graph_with_nodes(
        Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Base", canonical_id=node_id)
    )
    current = _graph_with_nodes(
        Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Current", canonical_id=node_id)
    )
    other = _graph_with_nodes(
        Node(id=node_id, label="OpenAI", tags=["business_context"], brief="Incoming", canonical_id=node_id),
        _entity("Anthropic"),
    )

    result = merge_graphs(base, current, other)

    assert result.summary["conflict_classes"]["DIRECT"] >= 1
    assert result.summary["conflict_classes"]["NOVEL"] == 1
