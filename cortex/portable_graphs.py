from __future__ import annotations

import copy
import json
from typing import Any

from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory import AggressiveExtractor
from cortex.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.extract_memory_context import normalize_text
from cortex.temporal import apply_temporal_review_policy


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(item))
    return deduped


def _clone_graph(graph: CortexGraph) -> CortexGraph:
    return CortexGraph.from_v5_json(graph.export_v5())


def _node_terms(node: Node) -> set[str]:
    terms = {normalize_text(node.label)}
    terms.update(normalize_text(alias) for alias in node.aliases if str(alias).strip())
    if node.canonical_id:
        terms.add(normalize_text(node.canonical_id))
    return {term for term in terms if term}


def merge_graphs(base: CortexGraph, incoming: CortexGraph) -> CortexGraph:
    merged = _clone_graph(base)
    existing_by_label: dict[str, Node] = {}
    for node in merged.nodes.values():
        for term in _node_terms(node):
            existing_by_label[term] = node
    id_map: dict[str, str] = {}

    for new_node in incoming.nodes.values():
        existing = None
        for term in _node_terms(new_node):
            existing = existing_by_label.get(term)
            if existing is not None:
                break
        if existing is None:
            merged.add_node(copy.deepcopy(new_node))
            for term in _node_terms(merged.nodes[new_node.id]):
                existing_by_label[term] = merged.nodes[new_node.id]
            id_map[new_node.id] = new_node.id
            continue

        id_map[new_node.id] = existing.id
        existing.confidence = max(existing.confidence, new_node.confidence)
        existing.mention_count += max(new_node.mention_count, 1)
        existing.tags = list(dict.fromkeys(existing.tags + new_node.tags))
        existing.aliases = list(dict.fromkeys(existing.aliases + new_node.aliases))
        existing.metrics = list(dict.fromkeys(existing.metrics + new_node.metrics))
        existing.timeline = list(dict.fromkeys(existing.timeline + new_node.timeline))
        existing.source_quotes = list(dict.fromkeys(existing.source_quotes + new_node.source_quotes))
        existing.provenance = _dedupe_dicts(existing.provenance + new_node.provenance)
        existing.properties = {**existing.properties, **new_node.properties}
        if normalize_text(existing.label) != normalize_text(new_node.label):
            existing.aliases = list(dict.fromkeys(existing.aliases + [new_node.label]))
        if len(new_node.brief) > len(existing.brief):
            existing.brief = new_node.brief
        if len(new_node.full_description) > len(existing.full_description):
            existing.full_description = new_node.full_description
        if new_node.status:
            existing.status = new_node.status
        if new_node.valid_from and (not existing.valid_from or new_node.valid_from < existing.valid_from):
            existing.valid_from = new_node.valid_from
        if new_node.valid_to and (not existing.valid_to or new_node.valid_to > existing.valid_to):
            existing.valid_to = new_node.valid_to
        if new_node.first_seen and (not existing.first_seen or new_node.first_seen < existing.first_seen):
            existing.first_seen = new_node.first_seen
        if new_node.last_seen and (not existing.last_seen or new_node.last_seen > existing.last_seen):
            existing.last_seen = new_node.last_seen
        for term in _node_terms(existing):
            existing_by_label[term] = existing

    for edge in incoming.edges.values():
        src = id_map.get(edge.source_id, edge.source_id)
        tgt = id_map.get(edge.target_id, edge.target_id)
        if src not in merged.nodes or tgt not in merged.nodes:
            continue
        edge_copy = copy.deepcopy(edge)
        edge_copy.source_id = src
        edge_copy.target_id = tgt
        merged.add_edge(edge_copy)

    return merged


def create_fallback_graph(statement: str, *, tags: list[str] | None = None, confidence: float = 0.85) -> CortexGraph:
    graph = CortexGraph()
    cleaned = " ".join(statement.split()).strip()
    label = cleaned[:72].rstrip(".")
    node_tags = tags or ["active_priorities"]
    graph.add_node(
        Node(
            id=make_node_id_with_tag(label, node_tags[0]),
            label=label,
            tags=node_tags,
            confidence=confidence,
            brief=cleaned,
            full_description=cleaned,
            provenance=[{"source": "portable.remember", "method": "manual"}],
        )
    )
    return graph


def extract_graph_from_statement(statement: str, *, confidence: float = 0.85) -> CortexGraph:
    extractor = AggressiveExtractor()
    extractor.extract_from_text(statement)
    extractor.post_process()
    payload = extractor.context.export()
    graph = upgrade_v4_to_v5(payload)
    if graph.nodes:
        apply_temporal_review_policy(graph)
        return graph
    return create_fallback_graph(statement, confidence=confidence)


__all__ = [
    "create_fallback_graph",
    "extract_graph_from_statement",
    "merge_graphs",
]
