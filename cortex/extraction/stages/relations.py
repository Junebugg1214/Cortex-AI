from __future__ import annotations

from dataclasses import replace
from time import perf_counter

from cortex.extraction.extract_memory_context import (
    ExtractedFact,
    ExtractedMemoryItem,
    ExtractedRelationship,
    normalize_text,
)

from .state import PipelineState


def _register_endpoint(label_to_id: dict[str, str], label: str, node_id: str) -> None:
    norm = normalize_text(label)
    if norm and node_id:
        label_to_id[norm] = node_id


def _endpoint_map(items: tuple[ExtractedMemoryItem, ...], state: PipelineState) -> dict[str, str]:
    label_to_id: dict[str, str] = {}
    for item in items:
        if isinstance(item, ExtractedRelationship):
            continue
        endpoint_id = item.entity_resolution or item.topic
        _register_endpoint(label_to_id, item.topic, endpoint_id)
        _register_endpoint(label_to_id, item.brief, endpoint_id)
        if isinstance(item, ExtractedFact):
            _register_endpoint(label_to_id, item.attribute_value, endpoint_id)

    graph = state.context.existing_graph
    if graph is not None:
        for node in graph.nodes.values():
            endpoint_id = node.canonical_id or node.id
            _register_endpoint(label_to_id, node.label, endpoint_id)
            for alias in node.aliases:
                _register_endpoint(label_to_id, alias, endpoint_id)
    return label_to_id


def link_relations(state: PipelineState) -> PipelineState:
    """Bind relationships to canonical endpoints and drop dangling links."""

    started = perf_counter()
    label_to_id = _endpoint_map(state.items, state)
    linked_items: list[ExtractedMemoryItem] = []
    dropped = 0

    for item in state.items:
        if not isinstance(item, ExtractedRelationship):
            linked_items.append(item)
            continue
        source_id = label_to_id.get(normalize_text(item.source_label))
        target_id = label_to_id.get(normalize_text(item.target_label))
        if not source_id or not target_id:
            dropped += 1
            continue
        qualifiers = dict(item.qualifiers)
        qualifiers.update({"source_id": source_id, "target_id": target_id})
        linked_items.append(replace(item, qualifiers=qualifiers))

    metadata = dict(state.metadata)
    metadata["dropped_dangling_relationships"] = int(metadata.get("dropped_dangling_relationships", 0)) + dropped
    next_state = replace(state, items=tuple(linked_items), metadata=metadata)
    return next_state.with_timing("link_relations", (perf_counter() - started) * 1000.0)
