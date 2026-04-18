from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Any

from cortex.extraction.extract_memory_context import ExtractedFact, ExtractedMemoryItem, normalize_text
from cortex.extraction.pipeline import _apply_existing_graph_resolutions
from cortex.extraction.prompts import load_prompt
from cortex.extraction.retrieval import retrieve_similar_nodes
from cortex.graph import Node
from cortex.versioning.merge import CanonicalEntityRegistry

from .state import PipelineState

CANONICALIZE_PROMPT = load_prompt("canonicalize", "v1")
PROMPT_REFERENCES = (CANONICALIZE_PROMPT.reference,)


def _item_aliases(item: ExtractedMemoryItem) -> list[str]:
    aliases = [item.topic, item.brief]
    if isinstance(item, ExtractedFact):
        aliases.append(item.attribute_value)
    return [alias.strip() for alias in aliases if alias and alias.strip()]


def _with_entity_resolution(item: ExtractedMemoryItem, node_id: str) -> ExtractedMemoryItem:
    return replace(item, entity_resolution=node_id)


def _registry_match(item: ExtractedMemoryItem, registry: CanonicalEntityRegistry | None) -> str:
    if registry is None:
        return ""
    for alias in _item_aliases(item):
        node = Node(
            id=f"candidate:{normalize_text(alias)}", label=alias, tags=[item.category], confidence=item.confidence
        )
        matched = registry.match(node)
        if matched is not None:
            return matched.id
    return ""


def _retrieval_match(
    item: ExtractedMemoryItem,
    *,
    embedding_backend: Any,
    graph: Any,
    top_k: int,
    threshold: float,
) -> str:
    if embedding_backend is None or graph is None:
        return ""
    text = " ".join(_item_aliases(item))
    if not text:
        return ""
    hints = retrieve_similar_nodes(embedding_backend, graph, text, top_k=top_k, threshold=threshold)
    return hints[0].node_id if hints else ""


def link_to_graph(
    state: PipelineState,
    *,
    embedding_backend: Any = None,
    retrieval_top_k: int = 8,
    retrieval_threshold: float = 0.72,
) -> PipelineState:
    """Resolve candidate items against retrieval hints and the canonical entity registry."""

    started = perf_counter()
    graph = state.context.existing_graph
    registry = CanonicalEntityRegistry(graph) if graph is not None else None
    linked_items: list[ExtractedMemoryItem] = []
    warnings = list(state.warnings)

    for item in state.items:
        resolved = state.context.canonical_resolver.resolve(item, graph)
        if not resolved.entity_resolution:
            node_id = _registry_match(resolved, registry)
            if not node_id:
                try:
                    node_id = _retrieval_match(
                        resolved,
                        embedding_backend=embedding_backend,
                        graph=graph,
                        top_k=retrieval_top_k,
                        threshold=retrieval_threshold,
                    )
                except Exception:
                    node_id = ""
                    if "canonicalize_retrieval_failed" not in warnings:
                        warnings.append("canonicalize_retrieval_failed")
            if node_id:
                resolved = _with_entity_resolution(resolved, node_id)
        linked_items.append(resolved)

    _apply_existing_graph_resolutions(linked_items, graph)
    next_state = replace(state, items=tuple(linked_items), warnings=tuple(warnings))
    if warnings != list(state.warnings):
        next_state = next_state.with_warnings(tuple(warnings))
    return next_state.with_timing("link_to_graph", (perf_counter() - started) * 1000.0)
