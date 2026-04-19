from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cortex.graph.graph import CortexGraph


@dataclass(frozen=True)
class NodeHint:
    """Existing graph node surfaced as retrieval context for model extraction."""

    node_id: str
    label: str
    type: str
    confidence: float
    similarity: float


def _node_type(node: Any) -> str:
    tags = list(getattr(node, "tags", []) or [])
    if tags:
        return str(tags[0])
    return str(getattr(node, "type", "") or "mentions")


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hint_from_search_result(result: Any, *, threshold: float) -> NodeHint | None:
    if isinstance(result, NodeHint):
        return result if result.similarity >= threshold else None
    if not isinstance(result, dict):
        return None

    node = result.get("node")
    node_id = str(result.get("id") or result.get("node_id") or getattr(node, "id", "") or "").strip()
    label = str(result.get("label") or getattr(node, "label", "") or "").strip()
    similarity = _float_value(result.get("similarity", result.get("score")), default=0.0)
    if not node_id or not label or similarity < threshold:
        return None
    return NodeHint(
        node_id=node_id,
        label=label,
        type=str(result.get("type") or _node_type(node)),
        confidence=_float_value(result.get("confidence", getattr(node, "confidence", 0.0)), default=0.0),
        similarity=similarity,
    )


def retrieve_similar_nodes(
    embedding_backend: Any,
    graph: CortexGraph | None,
    chunk_text: str,
    top_k: int = 8,
    threshold: float = 0.72,
) -> list[NodeHint]:
    """Retrieve existing graph nodes semantically similar to a chunk."""

    if top_k <= 0 or embedding_backend is None or graph is None or not chunk_text.strip() or not graph.nodes:
        return []

    nodes = list(graph.nodes.values())
    if hasattr(embedding_backend, "search_nodes"):
        raw_results = embedding_backend.search_nodes(chunk_text, nodes, top_k=top_k, threshold=threshold)
    else:
        embedding_backend.build_index(nodes)
        raw_results = embedding_backend.search(chunk_text, top_k=top_k, threshold=threshold)

    hints: list[NodeHint] = []
    seen_ids: set[str] = set()
    for result in raw_results or []:
        hint = _hint_from_search_result(result, threshold=threshold)
        if hint is None or hint.node_id in seen_ids:
            continue
        seen_ids.add(hint.node_id)
        hints.append(hint)
        if len(hints) >= top_k:
            break
    return hints
